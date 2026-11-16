"""SQLite storage. One file per app data dir; nothing shared with other apps.

The schema keeps owner_id everywhere so a later move to PostgreSQL (Neon, dedicated
branch/schema) does not need a redesign.
"""
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from .util import now, digest, encode

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows(
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL, version INTEGER NOT NULL,
  doc TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workflow_versions(
  workflow_id TEXT NOT NULL, version INTEGER NOT NULL, doc TEXT NOT NULL, doc_digest TEXT NOT NULL,
  saved_at TEXT NOT NULL, note TEXT NOT NULL, PRIMARY KEY(workflow_id, version));
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, workflow_id TEXT, workflow_version INTEGER,
  doc TEXT NOT NULL, doc_digest TEXT NOT NULL, status TEXT NOT NULL, cutoff TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
  current_step TEXT, order_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS node_runs(
  run_id TEXT NOT NULL, node_id TEXT NOT NULL, node_type TEXT NOT NULL, status TEXT NOT NULL,
  reason TEXT, error_code TEXT, started_at TEXT, finished_at TEXT, heartbeat_at TEXT,
  input_digests TEXT NOT NULL DEFAULT '[]', output_packet TEXT, steps TEXT NOT NULL DEFAULT '[]',
  tool_calls INTEGER NOT NULL DEFAULT 0, model_calls INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(run_id, node_id));
CREATE TABLE IF NOT EXISTS packets(
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, node_id TEXT NOT NULL, type TEXT NOT NULL,
  header TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calls(
  idempotency_key TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at TEXT NOT NULL, result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS broker_reports(
  file TEXT PRIMARY KEY, sha256 TEXT NOT NULL, data TEXT NOT NULL, scanned_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS broker_candidates(
  id TEXT PRIMARY KEY, file TEXT NOT NULL, sha256 TEXT NOT NULL, data TEXT NOT NULL, state TEXT NOT NULL,
  review_value_mn TEXT, review_note TEXT, reviewed_at TEXT, reviewer TEXT, extracted_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_runs(
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  status TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS objections(
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS crowd_assumptions(
  owner_id TEXT NOT NULL, ticker TEXT NOT NULL, fiscal_year INTEGER NOT NULL, metric TEXT NOT NULL, period TEXT NOT NULL,
  value_mn TEXT NOT NULL, submitted_at TEXT NOT NULL, PRIMARY KEY(owner_id, ticker, fiscal_year, metric, period));
CREATE TABLE IF NOT EXISTS broker_forecasts_v2(
  id TEXT PRIMARY KEY, file TEXT NOT NULL, sha256 TEXT NOT NULL, ticker TEXT, kind TEXT NOT NULL, metric TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL, quarter INTEGER, data TEXT NOT NULL, state TEXT NOT NULL, reviewer TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, owner_id TEXT NOT NULL,
  action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT NOT NULL);
"""

ACTIVE = ('waiting', 'running')


class NotFound(KeyError):
    pass


class Store:
    def __init__(self, data_dir):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / 'nodes.sqlite'
        self.lock = threading.RLock()
        with self.connect() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        """Commit on success, roll back on error, and always close (Windows file locks)."""
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c:
                yield c
        finally:
            c.close()

    def audit(self, c, owner, action, target, detail=None):
        c.execute('INSERT INTO audit(at,owner_id,action,target,detail) VALUES(?,?,?,?,?)',
                  (now(), owner, action, target, encode(detail or {})))

    # ---- startup recovery ------------------------------------------------
    def mark_interrupted(self):
        """Server restart: anything that was in flight is interrupted, never re-run."""
        with self.lock, self.connect() as c:
            t = now()
            n = c.execute(f"UPDATE node_runs SET status='interrupted', reason='서버 재시작으로 중단됨. 자동으로 다시 실행하지 않습니다.', finished_at=? WHERE status IN {ACTIVE}", (t,)).rowcount
            r = c.execute(f"UPDATE runs SET status='interrupted', finished_at=?, current_step=NULL WHERE status IN {ACTIVE}", (t,)).rowcount
            return r, n

    # ---- workflows ---------------------------------------------------------
    def save_workflow(self, owner, doc, workflow_id=None, note='저장'):
        with self.lock, self.connect() as c:
            t = now()
            if workflow_id:
                row = c.execute('SELECT * FROM workflows WHERE id=? AND owner_id=?', (workflow_id, owner)).fetchone()
                if not row:
                    raise NotFound(workflow_id)
                version = row['version'] + 1
                if row['name'] != doc['name']:
                    note = f"이름 변경: {row['name']} → {doc['name']}" + ('' if note == '저장' else f' / {note}')
                c.execute('UPDATE workflows SET name=?, version=?, doc=?, updated_at=? WHERE id=?',
                          (doc['name'], version, encode(doc), t, workflow_id))
            else:
                workflow_id = uuid.uuid4().hex
                version = 1
                c.execute('INSERT INTO workflows VALUES(?,?,?,?,?,?,?)', (workflow_id, owner, doc['name'], version, encode(doc), t, t))
            c.execute('INSERT INTO workflow_versions VALUES(?,?,?,?,?,?)', (workflow_id, version, encode(doc), digest(doc), t, note))
            self.audit(c, owner, 'workflow.save', workflow_id, {'version': version, 'note': note})
            return workflow_id, version

    def get_workflow(self, owner, workflow_id):
        with self.connect() as c:
            row = c.execute('SELECT * FROM workflows WHERE id=? AND owner_id=?', (workflow_id, owner)).fetchone()
            if not row:
                raise NotFound(workflow_id)
            versions = [dict(v) for v in c.execute(
                'SELECT version, saved_at, note, doc_digest FROM workflow_versions WHERE workflow_id=? ORDER BY version DESC', (workflow_id,))]
            return {'id': row['id'], 'name': row['name'], 'version': row['version'], 'doc': json.loads(row['doc']),
                    'updated_at': row['updated_at'], 'history': versions}

    def list_workflows(self, owner):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT id, name, version, updated_at FROM workflows WHERE owner_id=? ORDER BY updated_at DESC', (owner,))]

    # ---- runs ----------------------------------------------------------------
    def create_run(self, owner, doc, order, workflow_id=None, workflow_version=None):
        run_id = uuid.uuid4().hex
        with self.lock, self.connect() as c:
            t = now()
            c.execute('INSERT INTO runs(id,owner_id,workflow_id,workflow_version,doc,doc_digest,status,cutoff,created_at,order_json) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (run_id, owner, workflow_id, workflow_version, encode(doc), digest(doc), 'waiting', doc.get('cutoff'), t, encode(order)))
            types = {n['id']: n['type'] for n in doc['nodes']}
            for nid in order:
                c.execute("INSERT INTO node_runs(run_id,node_id,node_type,status) VALUES(?,?,?,'waiting')", (run_id, nid, types[nid]))
            self.audit(c, owner, 'run.create', run_id, {'workflow_id': workflow_id, 'version': workflow_version})
        return run_id

    def update_run(self, run_id, **kw):
        with self.lock, self.connect() as c:
            sets = ', '.join(f'{k}=?' for k in kw)
            c.execute(f'UPDATE runs SET {sets} WHERE id=?', (*kw.values(), run_id))

    def update_node(self, run_id, node_id, **kw):
        if 'input_digests' in kw:
            kw['input_digests'] = encode(kw['input_digests'])
        if 'steps' in kw:
            kw['steps'] = encode(kw['steps'])
        with self.lock, self.connect() as c:
            sets = ', '.join(f'{k}=?' for k in kw)
            c.execute(f'UPDATE node_runs SET {sets} WHERE run_id=? AND node_id=?', (*kw.values(), run_id, node_id))

    def cancel_requested(self, run_id):
        with self.connect() as c:
            row = c.execute('SELECT cancel_requested FROM runs WHERE id=?', (run_id,)).fetchone()
            return bool(row and row[0])

    def request_cancel(self, owner, run_id):
        with self.lock, self.connect() as c:
            row = c.execute('SELECT status FROM runs WHERE id=? AND owner_id=?', (run_id, owner)).fetchone()
            if not row:
                raise NotFound(run_id)
            if row['status'] not in ACTIVE:
                return row['status']
            c.execute('UPDATE runs SET cancel_requested=1 WHERE id=?', (run_id,))
            self.audit(c, owner, 'run.cancel', run_id)
            return 'cancelling'

    def get_run(self, owner, run_id):
        with self.connect() as c:
            row = c.execute('SELECT * FROM runs WHERE id=? AND owner_id=?', (run_id, owner)).fetchone()
            if not row:
                raise NotFound(run_id)
            nodes = []
            for n in c.execute('SELECT * FROM node_runs WHERE run_id=?', (run_id,)):
                d = dict(n)
                d['input_digests'] = json.loads(d['input_digests'])
                d['steps'] = json.loads(d['steps'])
                nodes.append(d)
            order = json.loads(row['order_json'])
            nodes.sort(key=lambda d: order.index(d['node_id']))
            run = dict(row)
            run['doc'] = json.loads(run['doc'])
            run['order'] = order
            del run['order_json']
            run['nodes'] = nodes
            return run

    def list_runs(self, owner, workflow_id=None):
        q = 'SELECT id, workflow_id, workflow_version, status, created_at, finished_at, cutoff FROM runs WHERE owner_id=?'
        args = [owner]
        if workflow_id:
            q += ' AND workflow_id=?'
            args.append(workflow_id)
        with self.connect() as c:
            return [dict(r) for r in c.execute(q + ' ORDER BY created_at DESC LIMIT 50', args)]

    # ---- packets -----------------------------------------------------------
    def put_packet(self, header, payload):
        pid = header['packet_id']
        with self.lock, self.connect() as c:
            c.execute('INSERT OR REPLACE INTO packets VALUES(?,?,?,?,?,?)',
                      (pid, header['run_id'], header['produced_by']['node_id'], header['type'], encode(header), encode(payload)))
        return pid

    def get_packet(self, packet_id, owner=None):
        with self.connect() as c:
            row = c.execute('SELECT p.*, r.owner_id FROM packets p JOIN runs r ON r.id=p.run_id WHERE p.id=?', (packet_id,)).fetchone()
            if not row or (owner is not None and row['owner_id'] != owner):
                raise NotFound(packet_id)
            return {'header': json.loads(row['header']), 'payload': json.loads(row['payload'])}

    # ---- idempotent calls --------------------------------------------------
    def call_result(self, key):
        with self.connect() as c:
            row = c.execute('SELECT result FROM calls WHERE idempotency_key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def put_call(self, key, kind, result):
        with self.lock, self.connect() as c:
            c.execute('INSERT OR IGNORE INTO calls VALUES(?,?,?,?)', (key, kind, now(), encode(result)))

    # ---- agent runs (additive; existing tables untouched) ----------------
    def agent_save(self, owner, aid, status, data):
        t = now()
        with self.lock, self.connect() as c:
            if c.execute('SELECT 1 FROM agent_runs WHERE id=? AND owner_id=?', (aid, owner)).fetchone():
                c.execute('UPDATE agent_runs SET status=?, data=?, updated_at=? WHERE id=?', (status, encode(data), t, aid))
            else:
                c.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?)', (aid, owner, t, t, status, encode(data)))

    def agent_mark_interrupted(self):
        with self.lock, self.connect() as c:
            rows = c.execute("SELECT id, data FROM agent_runs WHERE status='running'").fetchall()
            for r in rows:
                d = json.loads(r['data']); d['note'] = '서버가 다시 시작되어 에이전트 실행이 중단됐습니다.'
                c.execute("UPDATE agent_runs SET status='interrupted', data=?, updated_at=? WHERE id=?", (encode(d), now(), r['id']))
            return len(rows)

    def agent_get(self, owner, aid):
        with self.connect() as c:
            r = c.execute('SELECT * FROM agent_runs WHERE id=? AND owner_id=?', (aid, owner)).fetchone()
            if not r:
                raise NotFound(aid)
            return json.loads(r['data']) | {'id': r['id'], 'status': r['status'], 'created_at': r['created_at'], 'updated_at': r['updated_at']}

    def objection_save(self, owner, oid, data):
        with self.lock, self.connect() as c:
            c.execute('INSERT INTO objections VALUES(?,?,?,?)', (oid, owner, now(), encode(data)))
            self.audit(c, owner, 'objection.create', oid, {k: data.get(k) for k in ('base_run', 'node', 'field', 'kind', 'agent_run')})

    def objection_get(self, owner, oid):
        with self.connect() as c:
            r = c.execute('SELECT * FROM objections WHERE id=? AND owner_id=?', (oid, owner)).fetchone()
            if not r:
                raise NotFound(oid)
            return json.loads(r['data']) | {'id': r['id'], 'created_at': r['created_at']}

    def audit_details(self, owner, action, limit=2000):
        with self.connect() as c:
            rows = c.execute('SELECT detail FROM audit WHERE owner_id=? AND action=? ORDER BY id DESC LIMIT ?', (owner, action, limit)).fetchall()
            return [json.loads(r['detail']) for r in rows]

    def agent_audit(self, owner, action, target, detail):
        with self.lock, self.connect() as c:
            self.audit(c, owner, action, target, detail)

    # ---- broker forecast candidates ---------------------------------------
    def broker_upsert(self, owner, reports, cands):
        """Store a scan. Existing reviews survive only if the extracted value and file hash are unchanged."""
        t = now()
        kept = reset = new = 0
        with self.lock, self.connect() as c:
            names = [r['file'] for r in reports]
            c.execute(f"DELETE FROM broker_reports WHERE file NOT IN ({','.join('?' * len(names))})", names)  # renamed/removed files
            for r in reports:
                c.execute('INSERT OR REPLACE INTO broker_reports VALUES(?,?,?,?)', (r['file'], r['sha256'], encode(r), t))
            seen = set()
            for x in cands:
                seen.add(x['id'])
                old = c.execute('SELECT * FROM broker_candidates WHERE id=?', (x['id'],)).fetchone()
                if old and json.loads(old['data'])['value_mn'] == x['value_mn'] and old['sha256'] == x['sha256'] and old['state'] != 'stale':
                    c.execute('UPDATE broker_candidates SET data=?, file=? WHERE id=?', (encode(x), x['file'], x['id']))
                    kept += 1
                    continue
                if old:
                    reset += 1
                    self.audit(c, owner, 'broker.candidate_reset', x['id'], {'reason': '추출값 또는 파일 해시 변경', 'old_state': old['state']})
                else:
                    new += 1
                c.execute('INSERT OR REPLACE INTO broker_candidates(id,file,sha256,data,state,extracted_at) VALUES(?,?,?,?,?,?)',
                          (x['id'], x['file'], x['sha256'], encode(x), 'proposed', t))
            for row in c.execute('SELECT id FROM broker_candidates WHERE state != ?', ('stale',)).fetchall():
                if row['id'] not in seen:
                    c.execute("UPDATE broker_candidates SET state='stale' WHERE id=?", (row['id'],))
            self.audit(c, owner, 'broker.scan', 'broker_reports', {'reports': len(reports), 'candidates': len(cands), 'kept': kept, 'reset': reset, 'new': new})
        return {'kept': kept, 'reset': reset, 'new': new}

    def broker_reports(self):
        with self.connect() as c:
            reps = [json.loads(r['data']) | {'scanned_at': r['scanned_at']} for r in c.execute('SELECT * FROM broker_reports ORDER BY file')]
            cands = []
            for r in c.execute('SELECT * FROM broker_candidates ORDER BY id'):
                d = json.loads(r['data'])
                d.update(state=r['state'], review_value_mn=r['review_value_mn'], review_note=r['review_note'], reviewed_at=r['reviewed_at'])
                d['effective_value_mn'] = r['review_value_mn'] or d['value_mn']
                cands.append(d)
            return reps, cands

    # ---- v0.24 분기·순이익 전망 (새 표 — 기존 broker_candidates는 건드리지 않음) -----------------
    def v2_forecasts_put(self, owner, rows, reviewer):
        """rows: broker_quarter 미리 보기 행. 이미 있는 id는 그대로 둔다(사람이 바꾼 상태 보존). 자동 확인 통과 = approved, 아니면 proposed."""
        new = 0
        with self.lock, self.connect() as c:
            for r in rows:
                kind = 'quarter' if r.get('quarter') not in (None, '') else 'annual'
                rid = f"{r['sha256'][:12]}:{kind}:{r['metric']}:{r['fiscal_year']}" + (f"Q{r['quarter']}" if kind == 'quarter' else '')
                if c.execute('SELECT 1 FROM broker_forecasts_v2 WHERE id=?', (rid,)).fetchone():
                    continue
                st = 'approved' if r.get('auto_ok') in (True, 'True') else 'proposed'
                c.execute('INSERT INTO broker_forecasts_v2 VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                          (rid, r['file'], r['sha256'], r.get('ticker'), kind, r['metric'], int(r['fiscal_year']),
                           int(r['quarter']) if kind == 'quarter' else None, json.dumps(r, ensure_ascii=False), st, reviewer if st == 'approved' else None, now()))
                new += 1
            self.audit(c, owner, 'broker.v2_put', 'broker_forecasts_v2', {'rows': len(rows), 'new': new, 'reviewer': reviewer})
        return new

    def v2_forecasts_revert(self, owner, reviewer):
        with self.lock, self.connect() as c:
            n = c.execute('DELETE FROM broker_forecasts_v2 WHERE reviewer=?', (reviewer,)).rowcount
            self.audit(c, owner, 'broker.v2_revert', 'broker_forecasts_v2', {'deleted': n, 'reviewer': reviewer})
        return n

    def v2_forecasts(self, ticker=None, state='approved'):
        with self.connect() as c:
            q, a = 'SELECT * FROM broker_forecasts_v2 WHERE state=?', [state]
            if ticker:
                q += ' AND ticker=?'; a.append(ticker)
            return [json.loads(r['data']) | {'id': r['id'], 'kind': r['kind'], 'state': r['state'], 'reviewer': r['reviewer']} for r in c.execute(q + ' ORDER BY id', a)]

    def v2_counts(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT kind, metric, state, COUNT(*) n FROM broker_forecasts_v2 GROUP BY kind, metric, state')]

    # ---- 모두의 가정 (v0.18): 사람마다 한 달에 1건(같은 달 다시 내면 바뀜), 공개는 분포만 -----------------
    def crowd_submit(self, owner, ticker, fy, metric, value_mn, at=None):
        at = at or now()
        period = at[:7]
        with self.lock, self.connect() as c:
            c.execute('INSERT OR REPLACE INTO crowd_assumptions VALUES(?,?,?,?,?,?,?)', (owner, ticker, int(fy), metric, period, str(value_mn), at))
            self.audit(c, owner, 'crowd.submit', f'{ticker}:{fy}:{metric}', {'period': period})     # 값은 감사 기록에 남기지 않음
        return {'period': period, 'submitted_at': at}

    def crowd_mine(self, owner, ticker, fy, metric):
        with self.connect() as c:
            r = c.execute('SELECT value_mn, submitted_at, period FROM crowd_assumptions WHERE owner_id=? AND ticker=? AND fiscal_year=? AND metric=? '
                          'ORDER BY submitted_at DESC LIMIT 1', (owner, ticker, int(fy), metric)).fetchone()
            return dict(r) if r else None

    def crowd_values(self, ticker, fy, metric, until=None):
        """사람마다 until(포함) 이전의 가장 최근 값 1건."""
        q = 'SELECT owner_id, value_mn, submitted_at FROM crowd_assumptions WHERE ticker=? AND fiscal_year=? AND metric=?'
        args = [ticker, int(fy), metric]
        if until:
            q += ' AND submitted_at <= ?'; args.append(until)
        with self.connect() as c:
            last = {}
            for r in c.execute(q + ' ORDER BY submitted_at', args):
                last[r['owner_id']] = r['value_mn']
            return list(last.values())

    def crowd_monthly(self, ticker, fy, metric):
        """달마다(그 달 말까지) 사람별 최신 값 목록."""
        with self.connect() as c:
            rows = [dict(r) for r in c.execute('SELECT owner_id, value_mn, submitted_at, period FROM crowd_assumptions WHERE ticker=? AND fiscal_year=? AND metric=? '
                                               'ORDER BY submitted_at', (ticker, int(fy), metric))]
        out = {}
        for p in sorted({r['period'] for r in rows}):
            last = {}
            for r in rows:
                if r['period'] <= p:
                    last[r['owner_id']] = r['value_mn']
            out[p] = list(last.values())
        return out

    def broker_review(self, owner, cid, action, value_mn=None, note=''):
        states = {'approve': 'approved', 'reject': 'rejected', 'reset': 'proposed', 'edit': 'approved'}
        if action not in states:
            raise ValueError('unknown_action')
        with self.lock, self.connect() as c:
            row = c.execute('SELECT * FROM broker_candidates WHERE id=?', (cid,)).fetchone()
            if not row:
                raise NotFound(cid)
            if row['state'] == 'stale':
                raise ValueError('stale_candidate')
            if action == 'edit' and not (value_mn and note.strip()):
                raise ValueError('edit_needs_value_and_note')
            c.execute('UPDATE broker_candidates SET state=?, review_value_mn=?, review_note=?, reviewed_at=?, reviewer=? WHERE id=?',
                      (states[action], value_mn if action == 'edit' else None, note.strip() or None, now(), owner, cid))
            self.audit(c, owner, 'broker.review', cid, {'action': action, 'value_mn': value_mn, 'note': note})
            return states[action]
