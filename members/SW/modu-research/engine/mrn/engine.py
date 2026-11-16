"""Run executor. One run at a time; nodes execute in topological order.

State rules
- A node runs only if every required input has a packet from a succeeded/partial upstream.
  Otherwise it is held with the reason (never silently skipped as success).
- not_connected nodes are recorded as such immediately.
- Cancel: the current node's subprocess is killed; finished nodes keep their results;
  the rest become cancelled.
- Restart: in-flight runs become interrupted (Store.mark_interrupted); nothing auto-resumes.
"""
import threading
import time
from .specs import SPECS, with_defaults
from .util import digest, now
from .official import Cancelled
from .nodes import HANDLERS, Result
from .util import Integrity

USABLE = ('succeeded', 'partial')
OUT_TYPE = {k: (v['outputs'][0]['type'] if v['outputs'] else None) for k, v in SPECS.items()}


class Ctx:
    def __init__(self, engine, run_id, node_id, cutoff):
        self.engine, self.store, self.run_id, self.node_id, self.cutoff = engine, engine.store, run_id, node_id, cutoff
        self.steps, self.tools, self._last_beat = [], 0, 0

    def heartbeat(self, force=False):
        t = time.monotonic()
        if force or t - self._last_beat > 1.5:
            self._last_beat = t
            self.store.update_node(self.run_id, self.node_id, heartbeat_at=now())

    def step(self, msg):
        self.steps.append({'at': now(), 'msg': msg})
        self.store.update_node(self.run_id, self.node_id, steps=self.steps, heartbeat_at=now())
        self.store.update_run(self.run_id, current_step=f'{self.node_id}: {msg}')

    def tool_call(self):
        self.tools += 1
        self.store.update_node(self.run_id, self.node_id, tool_calls=self.tools)

    def cancelled(self):
        return self.store.cancel_requested(self.run_id)

    def upstream(self, node_id):
        return self.engine.upstream_states(self.run_id, node_id)


class Engine:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.active = None
        self.threads = {}

    def busy(self):
        return self.active is not None

    def start(self, owner, doc, order, workflow_id=None, workflow_version=None, background=True):
        with self.lock:
            if self.active is not None:
                raise RuntimeError('다른 실행이 진행 중입니다. 끝나거나 취소한 뒤 다시 실행하세요.')
            run_id = self.store.create_run(owner, doc, order, workflow_id, workflow_version)
            self.active = run_id
        if background:
            t = threading.Thread(target=self._run, args=(run_id, doc, order), daemon=True)
            self.threads[run_id] = t
            t.start()
        else:
            self._run(run_id, doc, order)
        return run_id

    # ------------------------------------------------------------------
    def upstream_states(self, run_id, node_id):
        doc = self._docs[run_id]
        states = {n['node_id']: n for n in self._nodes(run_id)}
        return [states[e['from_node']] for e in doc['edges'] if e['to_node'] == node_id and e['from_node'] in states]

    def _nodes(self, run_id):
        with self.store.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM node_runs WHERE run_id=?', (run_id,))]

    def _run(self, run_id, doc, order):
        self._docs = getattr(self, '_docs', {})
        self._docs[run_id] = doc
        nodes = {n['id']: {**n, 'config': with_defaults(n['type'], n['config'])} for n in doc['nodes']}
        produced = {}   # node_id -> packet dict
        status = {}
        self.store.update_run(run_id, status='running', started_at=now())
        try:
            for i, nid in enumerate(order):
                node = nodes[nid]
                spec = SPECS[node['type']]
                if self.store.cancel_requested(run_id):
                    for rest in order[i:]:
                        self.store.update_node(run_id, rest, status='cancelled', reason='사용자 취소로 실행하지 않음', finished_at=now())
                        status[rest] = 'cancelled'
                    break
                cutoff = (node['config'].get('cutoff') or doc.get('cutoff') or '').strip()
                ctx = Ctx(self, run_id, nid, cutoff)
                # gather inputs
                inputs, digests, blocked = {}, [], []
                for p in spec['inputs']:
                    edges = [e for e in doc['edges'] if e['to_node'] == nid and e['to_port'] == p['name']]
                    for e in edges:
                        if e['from_node'] in produced:
                            pkt = produced[e['from_node']]
                            inputs.setdefault(p['name'], []).append(pkt)
                            digests.append({'port': p['name'], 'from': e['from_node'], 'packet_id': pkt['header']['packet_id'],
                                            'payload_digest': pkt['header']['payload_digest'], 'upstream_status': status[e['from_node']]})
                        elif p['required'] and node['type'] != 'T05':
                            blocked.append(f"{p['label']} ← {e['from_node']}({status.get(e['from_node'], '?')})")
                    if p['required'] and not edges:
                        blocked.append(f"{p['label']} 미연결")
                self.store.update_node(run_id, nid, input_digests=digests)
                if spec['implementation'] == 'not_connected':
                    self.store.update_node(run_id, nid, status='not_connected', reason=spec['not_connected_reason'], finished_at=now(), started_at=now())
                    status[nid] = 'not_connected'
                    continue
                if blocked:
                    msg = '입력이 없어 실행하지 않았습니다: ' + ', '.join(blocked)
                    self.store.update_node(run_id, nid, status='held', reason=msg, error_code='upstream_unavailable', started_at=now(), finished_at=now())
                    status[nid] = 'held'
                    continue
                self.store.update_node(run_id, nid, status='running', started_at=now(), heartbeat_at=now())
                self.store.update_run(run_id, current_step=f"{nid}: {spec['display_name']} 시작")
                try:
                    res = HANDLERS[node['type']](node, inputs, ctx)
                except Cancelled:
                    res = Result('cancelled', '사용자 취소로 이 노드 실행을 멈췄습니다.')
                except Integrity as e:
                    res = Result('held', str(e), error_code='integrity')
                except ValueError as e:
                    res = Result('failed', str(e), error_code='value_error')
                except Exception as e:  # noqa: BLE001 - recorded, never hidden
                    res = Result('failed', f'{type(e).__name__}: {e}', error_code='internal_error')
                packet_id = None
                if res.payload is not None and res.status in ('succeeded', 'partial'):
                    header = {'type': OUT_TYPE[node['type']], 'produced_by': {'node_id': nid, 'node_type': node['type'], 'version': spec['version']},
                              'run_id': run_id, 'cutoff': cutoff, 'input_digests': [d['payload_digest'] for d in digests],
                              'payload_digest': digest(res.payload), 'created_at': now()}
                    header['packet_id'] = digest({'run': run_id, 'node': nid, 'payload': header['payload_digest']})
                    self.store.put_packet(header, res.payload)
                    produced[nid] = {'header': header, 'payload': res.payload}
                    packet_id = header['packet_id']
                elif res.payload is not None:
                    # held/failed with diagnostic payload: stored for inspection, never fed downstream
                    header = {'type': 'Diagnostic', 'produced_by': {'node_id': nid, 'node_type': node['type'], 'version': spec['version']},
                              'run_id': run_id, 'cutoff': cutoff, 'input_digests': [], 'payload_digest': digest(res.payload), 'created_at': now()}
                    header['packet_id'] = digest({'run': run_id, 'node': nid, 'diag': header['payload_digest']})
                    self.store.put_packet(header, res.payload)
                    packet_id = header['packet_id']
                self.store.update_node(run_id, nid, status=res.status, reason=res.reason, error_code=res.error_code,
                                       output_packet=packet_id, finished_at=now(), heartbeat_at=now())
                status[nid] = res.status
                if res.status == 'cancelled':
                    for rest in order[i + 1:]:
                        self.store.update_node(run_id, rest, status='cancelled', reason='사용자 취소로 실행하지 않음', finished_at=now())
                        status[rest] = 'cancelled'
                    break
            vals = set(status.values())
            if 'cancelled' in vals:
                final = 'cancelled'
            elif 'failed' in vals:
                final = 'failed'
            elif vals <= {'succeeded'}:
                final = 'succeeded'
            else:
                final = 'partial'
            self.store.update_run(run_id, status=final, finished_at=now(), current_step=None)
        except Exception as e:  # noqa: BLE001
            self.store.update_run(run_id, status='failed', finished_at=now(), current_step=f'엔진 오류: {e}')
        finally:
            with self.lock:
                if self.active == run_id:
                    self.active = None
