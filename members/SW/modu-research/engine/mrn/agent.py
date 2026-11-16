"""Rule-based self-correcting runner (agent level 3-4, no AI model required).

The agent drives the same validate/run path a person uses. It never edits node code,
never approves a broker forecast, never makes a trade judgement and never changes a
value that came from an official source. It only:
  - reads node status + error code after each run,
  - looks the pair up in a public rule table,
  - applies one of a few deterministic fixes (with the principle shown), or asks a person, or stops.
Every step is stored (agent_runs) and audited.
"""
import copy
import threading
import time
import uuid

from .util import now
from .workflow import WorkflowDoc, validate, blocking, topo_order

MAX_ITERS = 4

# Public rule table. scope 'run' = node status after a run, 'check' = pre-run validation issue.
RULES = [
    {'id': 'R01', 'scope': 'run', 'node': 'T04', 'status': 'held', 'code': 'report_not_selected', 'action': 'fix', 'fix': 'pick_report',
     'title': '보고서 미선택 → 원칙대로 고름',
     'why': '선택 원칙: 사람이 승인한 보고서 중, 필요한 연도의 매출액·영업이익이 모두 승인된 것만. 최근 보고서일 순, 같은 워크플로의 다른 T04와 다른 증권사 우선. 결과가 좋아 보이는 보고서를 고르지 않습니다.'},
    {'id': 'R02', 'scope': 'run', 'node': 'T04', 'status': 'held', 'code': 'no_approved', 'action': 'ask',
     'title': '고른 보고서에 승인 없음 → 사람에게 요청',
     'why': '사람이 고른 보고서를 에이전트가 몰래 바꾸지 않고, 승인도 대신하지 않습니다.', 'ask': '「증권사 전망」 → 「승인」 탭에서 이 보고서를 검토·승인하거나, T04에서 다른 보고서를 고르세요.'},
    {'id': 'R03', 'scope': 'run', 'node': 'T04', 'status': 'held', 'code': 'report_unknown', 'action': 'ask',
     'title': '보고서가 스캔 목록에 없음 → 사람에게 요청', 'why': '파일 이름이 바뀌었거나 스캔 전입니다.', 'ask': '「증권사 전망」 → 「PDF 다시 스캔」 후 T04에서 보고서를 다시 고르세요.'},
    {'id': 'R04', 'scope': 'run', 'node': 'T04', 'status': 'held', 'code': 'pdf_changed', 'action': 'ask',
     'title': 'PDF 해시 변경 → 사람에게 요청', 'why': '원본이 바뀌었으면 이전 승인을 쓸 수 없습니다.', 'ask': '「PDF 다시 스캔」 후 바뀐 값을 다시 승인하세요.'},
    {'id': 'R05', 'scope': 'run', 'node': 'N02', 'status': 'held', 'code': 'facts_missing', 'action': 'fix', 'fix': 'add_n01_metrics',
     'title': 'N02에 필요한 사실이 없음 → N01 조사 항목 추가',
     'why': '공식 원문에서 읽을 항목을 늘리는 것뿐이며, 값을 만들거나 바꾸지 않습니다.'},
    {'id': 'R06', 'scope': 'run', 'node': 'N02', 'status': 'held', 'code': 'unapproved_forecast', 'action': 'ask',
     'title': '미승인 전망 유입 → 사람에게 요청', 'why': '승인은 사람만 합니다.', 'ask': '「증권사 전망」에서 해당 보고서를 검토·승인하세요.'},
    {'id': 'R07', 'scope': 'run', 'node': 'N02', 'status': 'held', 'code': 'mixed_reports', 'action': 'ask',
     'title': '여러 보고서 섞임 → 사람에게 요청', 'why': '전망을 조용히 합치지 않습니다.', 'ask': 'N02 하나에 보고서 하나만 연결하세요.'},
    {'id': 'R08', 'scope': 'run', 'node': 'N02', 'status': 'held', 'code': 'forecast_scope', 'action': 'ask',
     'title': '전망 범위 불일치 → 사람에게 요청', 'why': '기업·연도가 맞지 않는 전망을 억지로 맞추지 않습니다.', 'ask': 'N02의 기업·기준연도와 보고서 범위를 확인하세요.'},
    {'id': 'R09', 'scope': 'run', 'node': '*', 'status': 'held', 'code': 'reverify_mismatch', 'action': 'stop',
     'title': '원문 재대조 불일치 → 중단', 'why': '공식 원문과 맞지 않는 사실은 자동으로 고치지 않습니다. 사람이 원인을 확인해야 합니다.'},
    {'id': 'R10', 'scope': 'run', 'node': '*', 'status': 'held', 'code': 'integrity', 'action': 'stop',
     'title': '무결성(해시) 오류 → 중단', 'why': '자료 연결이 끊긴 결과로는 계속하지 않습니다.'},
    {'id': 'R11', 'scope': 'run', 'node': '*', 'status': 'held', 'code': 'cutoff_before_corpus', 'action': 'ask',
     'title': '기준시점이 자료보다 이름 → 사람에게 요청', 'why': '기준시점은 질문의 일부라서 에이전트가 바꾸지 않습니다.', 'ask': '상단 기준시점을 비우거나 2026-11-02 이후로 정하세요.'},
    {'id': 'R12', 'scope': 'run', 'node': '*', 'status': 'held', 'code': 'future_cutoff', 'action': 'ask',
     'title': '미래 기준시점 → 사람에게 요청', 'why': '기준시점은 질문의 일부라서 에이전트가 바꾸지 않습니다.', 'ask': '상단 기준시점을 현재 이전으로 정하세요.'},
    {'id': 'R13', 'scope': 'run', 'node': '*', 'status': 'held', 'code': 'upstream_unavailable', 'action': 'follow',
     'title': '앞 노드가 막혀 대기 → 앞 노드 규칙을 따름', 'why': '원인은 앞 노드에 있습니다.'},
    {'id': 'R14', 'scope': 'run', 'node': '*', 'status': 'partial', 'code': '*', 'action': 'accept',
     'title': '일부 결과 → 받아들이고 한계 명시', 'why': '구현된 범위까지의 결과입니다. 요약에 「일부」로 표시합니다.'},
    {'id': 'R15', 'scope': 'run', 'node': '*', 'status': 'not_connected', 'code': '*', 'action': 'accept',
     'title': '미연결 노드 → 받아들이고 명시', 'why': '아직 자료원이 연결되지 않은 노드입니다.'},
    {'id': 'R16', 'scope': 'run', 'node': '*', 'status': 'failed', 'code': 'internal_error', 'action': 'retry',
     'title': '내부 오류 → 한 번만 재시도', 'why': '일시적 오류일 수 있습니다. 두 번째도 실패하면 멈춥니다.'},
    {'id': 'R17', 'scope': 'run', 'node': '*', 'status': 'interrupted', 'code': '*', 'action': 'retry',
     'title': '중단된 실행 → 한 번만 재시도', 'why': '서버 재시작 등으로 끊긴 경우입니다.'},
    {'id': 'R18', 'scope': 'check', 'node': '*', 'status': '-', 'code': 'n02_scope', 'action': 'fix', 'fix': 'add_n01_scope',
     'title': 'N02 기업·연도가 N01 범위 밖 → N01 범위 추가', 'why': '공식 원문에서 읽을 범위를 넓히는 것뿐입니다.'},
    {'id': 'R19', 'scope': 'check', 'node': '*', 'status': '-', 'code': 'not_connected_node', 'action': 'accept',
     'title': '미연결 노드 포함 경고 → 받아들임', 'why': '실행하면 「미연결」로 기록됩니다.'},
    {'id': 'R20', 'scope': 'check', 'node': '*', 'status': '-', 'code': 'cutoff_default', 'action': 'accept',
     'title': '기준시점 비어 있음 → 실행 시각 사용', 'why': '사람이 비워 둔 기준시점의 정해진 뜻입니다.'},
    {'id': 'R99', 'scope': '*', 'node': '*', 'status': '*', 'code': '*', 'action': 'ask',
     'title': '규칙에 없는 상황 → 사람에게 요청', 'why': '모르는 상황에서는 추측하지 않고 멈춥니다.', 'ask': '노드의 「상태·오류」 탭에서 이유를 확인하세요.'},
]
DONE_OK = {'succeeded'}
ACTION_LABEL = {'fix': '자동 수정', 'ask': '사람 확인 필요', 'stop': '중단', 'accept': '받아들임', 'retry': '재시도', 'follow': '앞 노드 따름'}


def match_rule(scope, node_type, status, code):
    for r in RULES:
        if r['scope'] not in (scope, '*'):
            continue
        if r['node'] not in (node_type, '*') or r['status'] not in (status, '*', '-'):
            continue
        if r['code'] not in ((code or ''), '*'):
            continue
        return r
    return RULES[-1]


class Agent:
    def __init__(self, store, engine, check_assumptions):
        self.store, self.engine, self.check = store, engine, check_assumptions
        self.threads = {}

    # ---------------------------------------------------------------- public
    def start(self, owner, doc, goal='', max_iters=MAX_ITERS):
        aid = uuid.uuid4().hex
        data = {'goal': goal, 'doc_initial': doc, 'doc_final': doc, 'steps': [], 'runs': [], 'asks': [], 'changes': [],
                'max_iters': max_iters, 'iteration': 0, 'final_run': None, 'note': ''}
        self.store.agent_save(owner, aid, 'running', data)
        self.store.agent_audit(owner, 'agent.start', aid, {'goal': goal, 'max_iters': max_iters})
        t = threading.Thread(target=self._loop, args=(owner, aid, copy.deepcopy(doc), data, max_iters), daemon=True)
        self.threads[aid] = t
        t.start()
        return aid

    # ---------------------------------------------------------------- loop
    def _loop(self, owner, aid, doc, data, max_iters):
        def log(kind, msg, **kw):
            data['steps'].append({'at': now(), 'iteration': data['iteration'], 'kind': kind, 'msg': msg} | kw)
            self.store.agent_save(owner, aid, 'running', data)

        retried = set()
        status = 'running'
        try:
            for it in range(1, max_iters + 1):
                data['iteration'] = it
                log('iter', f'{it}회차 시작')
                # 1) pre-run validation
                issues = validate(WorkflowDoc.model_validate(doc), self.check)
                pre_fix = False
                for iss in issues:
                    r = match_rule('check', '', '-', iss['code'])
                    if r['action'] == 'accept':
                        if iss['severity'] != 'error':
                            continue
                    if r['action'] == 'fix':
                        ch = self._fix(r['fix'], doc, iss, None)
                        if ch:
                            pre_fix = True
                            data['changes'] += ch
                            log('fix', f"[{r['id']}] {r['title']}", rule=r['id'], changes=ch, why=r['why'])
                            continue
                    if iss['severity'] == 'error':
                        ask = {'rule': r['id'], 'node': ','.join(iss.get('nodes') or []), 'message': iss['message'], 'ask': iss.get('fix') or r.get('ask', '')}
                        data['asks'].append(ask)
                        log('ask', f"[{r['id']}] 실행 전 검증 오류: {iss['message']}", rule=r['id'], why=r['why'])
                if pre_fix:
                    issues = validate(WorkflowDoc.model_validate(doc), self.check)
                if blocking(issues):
                    status = 'needs_human'
                    data['note'] = '실행 전 검증 오류가 남아 실행하지 않았습니다.'
                    break
                data['asks'] = []
                # 2) run (same engine path as the 실행 button)
                d = WorkflowDoc.model_validate(doc)
                if not d.cutoff:
                    d.cutoff = now()
                order = topo_order(d)
                for _ in range(50):
                    try:
                        run_id = self.engine.start(owner, d.model_dump(), order, None, None, background=False)
                        break
                    except RuntimeError:
                        time.sleep(0.2)
                else:
                    status = 'stopped'
                    data['note'] = '다른 실행이 계속 진행 중이라 시작하지 못했습니다.'
                    break
                run = self.store.get_run(owner, run_id)
                data['runs'].append({'iteration': it, 'run_id': run_id, 'status': run['status'],
                                     'nodes': [{'id': n['node_id'], 'type': n['node_type'], 'status': n['status'], 'code': n['error_code']} for n in run['nodes']]})
                data['final_run'] = run_id
                log('run', f"실행 {run_id[:8]} → {run['status']} (" + ', '.join(f"{n['node_id']} {n['status']}" for n in run['nodes']) + ')', run_id=run_id)
                # 3) read statuses and decide
                fixes, asks, stop, retry, accepts = [], [], None, False, []
                for n in run['nodes']:
                    if n['status'] in DONE_OK:
                        continue
                    r = match_rule('run', n['node_type'], n['status'], n['error_code'])
                    entry = {'rule': r['id'], 'node': n['node_id'], 'type': n['node_type'], 'status': n['status'], 'code': n['error_code'], 'reason': n['reason']}
                    if r['action'] == 'follow':
                        continue
                    if r['action'] == 'accept':
                        accepts.append(entry)
                        log('accept', f"[{r['id']}] {n['node_id']}: {r['title']}", rule=r['id'], why=r['why'], node=n['node_id'])
                    elif r['action'] == 'stop':
                        stop = entry
                        log('stop', f"[{r['id']}] {n['node_id']}: {r['title']} — {n['reason']}", rule=r['id'], why=r['why'], node=n['node_id'])
                    elif r['action'] == 'retry':
                        if n['node_id'] in retried:
                            stop = entry
                            log('stop', f"[{r['id']}] {n['node_id']}: 재시도 후에도 {n['status']}", rule=r['id'], node=n['node_id'])
                        else:
                            retried.add(n['node_id'])
                            retry = True
                            log('retry', f"[{r['id']}] {n['node_id']}: {r['title']}", rule=r['id'], why=r['why'], node=n['node_id'])
                    elif r['action'] == 'fix':
                        ch = self._fix(r['fix'], doc, None, n)
                        if ch:
                            fixes += ch
                            log('fix', f"[{r['id']}] {n['node_id']}: {r['title']}", rule=r['id'], changes=ch, why=r['why'], node=n['node_id'])
                        else:
                            r2 = next(x for x in RULES if x['id'] == 'R02') if r['fix'] == 'pick_report' else RULES[-1]
                            ask = entry | {'ask': '규칙상 고를 수 있는 승인 보고서가 없습니다. 「증권사 전망」 → 「승인」 탭에서 필요한 연도의 매출액·영업이익이 있는 보고서를 승인하세요.' if r['fix'] == 'pick_report' else r2.get('ask', '')}
                            asks.append(ask)
                            log('ask', f"[{r['id']}] {n['node_id']}: 자동 수정 불가 — 사람 확인 필요", rule=r['id'], node=n['node_id'], why=r['why'])
                    else:
                        asks.append(entry | {'ask': r.get('ask', '')})
                        log('ask', f"[{r['id']}] {n['node_id']}: {r['title']}", rule=r['id'], why=r['why'], node=n['node_id'])
                data['changes'] += fixes
                data['asks'] = asks
                data['accepted'] = accepts
                data['doc_final'] = doc
                if stop:
                    status = 'stopped'
                    data['note'] = f"{stop['node']}에서 중단 규칙({stop['rule']})이 적용됐습니다."
                    break
                if fixes or retry:
                    continue
                status = 'needs_human' if asks else 'completed'
                data['note'] = ('사람 확인이 필요한 항목이 있습니다.' if asks else
                                ('모든 노드가 성공했습니다.' if not accepts else '받아들인 한계(일부·미연결)를 빼고 모두 성공했습니다.'))
                break
            else:
                status = 'needs_human'
                data['note'] = f'최대 {max_iters}회 반복 안에 끝나지 않아 멈췄습니다.'
        except Exception as e:  # never leave an agent run dangling
            status = 'failed'
            data['note'] = f'{type(e).__name__}: {e}'
        data['doc_final'] = doc
        if data.get('final_run') and status != 'failed':
            try:
                from .gate import run_summary
                data['summary'] = run_summary(self.store, owner, data['final_run'])
                sm = data['summary']
                log('gate', f"근거 검증 관문: 문장 {len(sm['published'])}개 공개, {len(sm['held'])}개 보류 (근거 연결 값 {sm['bound']}개)")
            except Exception as e:  # the gate failing must never publish unchecked text
                data['summary'] = {'published': [], 'held': [], 'error': f'{type(e).__name__}: {e}'}
                log('gate', '근거 검증 관문 오류 — 요약을 공개하지 않았습니다.')
        log('end', f'종료: {status} — {data["note"]}')
        self.store.agent_save(owner, aid, status, data)
        self.store.agent_audit(owner, 'agent.end', aid, {'status': status, 'iterations': data['iteration'], 'changes': len(data['changes'])})

    # ---------------------------------------------------------------- fixes
    def _fix(self, kind, doc, issue, node_run):
        nodes = {n['id']: n for n in doc['nodes']}
        if kind == 'pick_report' and node_run:
            return self._pick_report(doc, nodes, node_run['node_id'])
        if kind == 'add_n01_metrics' and node_run:
            from .nodes import REQUIRED_FACTS
            n02 = nodes[node_run['node_id']]
            t03 = self._upstream(doc, n02['id'], 'assumptions')
            method = (nodes[t03]['config'].get('method') if t03 else None) or 'dcf'
            n01 = self._upstream(doc, n02['id'], 'facts')
            if not n01:
                return []
            cfg = nodes[n01]['config']
            before = list(cfg.get('metrics') or [])
            need = [m for m in REQUIRED_FACTS.get(method, []) if m not in before]
            if not need:
                return []
            cfg['metrics'] = before + need
            return [{'node': n01, 'field': 'metrics', 'before': before, 'after': cfg['metrics']}]
        if kind == 'add_n01_scope' and issue:
            out = []
            ids = issue.get('nodes') or []
            if len(ids) < 2 or ids[0] not in nodes or ids[1] not in nodes:
                return []
            n02, n01 = nodes[ids[0]], nodes[ids[1]]
            from .specs import with_defaults
            c2 = with_defaults('N02', n02['config'])
            c1 = n01['config']
            base = with_defaults('N01', c1)
            comps, years = list(base['companies']), list(base['years'])
            if c2['company'] not in comps:
                out.append({'node': n01['id'], 'field': 'companies', 'before': list(comps), 'after': comps + [c2['company']]})
                c1['companies'] = comps + [c2['company']]
            if int(c2['base_year']) not in [int(y) for y in years]:
                out.append({'node': n01['id'], 'field': 'years', 'before': list(years), 'after': sorted(years + [int(c2['base_year'])])})
                c1['years'] = sorted(years + [int(c2['base_year'])])
            return out
        return []

    @staticmethod
    def _upstream(doc, node_id, port):
        return next((e['from_node'] for e in doc['edges'] if e['to_node'] == node_id and e['to_port'] == port), None)

    def _pick_report(self, doc, nodes, t04_id):
        from .specs import with_defaults
        reports, cands = self.store.broker_reports()
        # which fiscal years does the downstream N02 need?
        n02 = next((e['to_node'] for e in doc['edges'] if e['from_node'] == t04_id and e['to_port'] == 'forecasts'), None)
        base, nyears = 2025, 2
        if n02:
            base = int(with_defaults('N02', nodes[n02]['config'])['base_year'])
            t03 = self._upstream(doc, n02, 'assumptions')
            if t03:
                yrs = ((nodes[t03]['config'].get('model') or {}).get('years')) or []
                nyears = max(1, len(yrs)) if isinstance(yrs, list) else 2
        need = [(base + 1 + i, m) for i in range(nyears) for m in ('revenue', 'operatingProfit')]
        ok = []
        for r in reports:
            a = {(c['fiscal_year'], c['metric']) for c in cands if c['file'] == r['file'] and c['state'] == 'approved' and c['sha256'] == r['sha256']}
            if all(x in a for x in need):
                ok.append(r)
        used_files = {n['config'].get('report') for n in doc['nodes'] if n['type'] == 'T04' and n['id'] != t04_id}
        used_brokers = {r['broker'] for r in reports if r['file'] in used_files}
        ok = [r for r in ok if r['file'] not in used_files]
        ok.sort(key=lambda r: r.get('report_date') or '', reverse=True)   # most recent first
        ok.sort(key=lambda r: r['broker'] in used_brokers)                 # then other brokers first (stable)
        if not ok:
            return []
        pick = ok[0]
        cfg = nodes[t04_id]['config']
        before = cfg.get('report', '')
        cfg['report'] = pick['file']
        return [{'node': t04_id, 'field': 'report', 'before': before, 'after': pick['file'],
                 'label': f"{pick.get('report_date')} {pick.get('broker')}", 'candidates': len(ok),
                 'need': [f'{fy} {"매출액" if m == "revenue" else "영업이익"}' for fy, m in need]}]
