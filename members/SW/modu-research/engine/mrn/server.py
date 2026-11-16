"""HTTP API + static UI. Local single-user app: owner cookie, double-submit CSRF, Origin check."""
import json
import os
import re
import secrets
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from .specs import REGISTRY, PERSPECTIVES, PORT_TYPES, KINDS, plan, plan_workflow
from .workflow import WorkflowDoc, validate, blocking, topo_order
from .store import Store, NotFound
from .engine import Engine
from .nodes import check_assumptions
from .util import now, instant
from . import numeric

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.0'
OWNER_COOKIE = 'mrn_owner'
CSRF_COOKIE = 'mrn_csrf'


class SaveBody(BaseModel):
    doc: dict
    note: str = '저장'


class CheckBody(BaseModel):
    text: str
    mode: str = 'research'
    question: str = ''
    run_id: str | None = None


class ReviewBody(BaseModel):
    id: str | None = None
    file: str | None = None
    action: str
    value_mn: str | None = None
    note: str = ''


class RagBody(BaseModel):
    query: str
    company: str | None = None
    k: int = 10
    mode: str = 'auto'
    synonyms: bool = True


class XbrlBody(BaseModel):
    company: str
    year: int = 2025
    refresh: bool = False


class ObjectionBody(BaseModel):
    run_id: str
    node_id: str
    field: str = ''
    value: str = ''
    reason: str


class AssembleBody(BaseModel):
    question: str = ''
    pick: list[str] | None = None
    cutoff: str = ''


class PlanBody(BaseModel):
    question: str
    persona: str | None = None
    use_model: bool = True


class GateBody(BaseModel):
    run_id: str
    text: str


class AgentBody(BaseModel):
    doc: dict
    goal: str = ''
    max_iters: int = 4


class EasyRunBody(BaseModel):
    card: str
    company: str
    cutoff: str = ''
    rcept_no: str = ''          # v0.38 T1: 「이 공시는 숫자로 무엇인가?」 카드만 씀


class RepairBody(BaseModel):
    run_id: str
    ids: list[str]


class CrowdBody(BaseModel):
    ticker: str
    fiscal_year: int
    metric: str
    value_jo: float          # 조 원 (화면 입력 단위)


class RegisterBody(BaseModel):
    file: str
    ticker: str
    broker: str
    report_date: str
    title: str = ''
    opinion: str = ''
    target_price: str = ''


class RunBody(BaseModel):
    doc: dict
    workflow_id: str | None = None
    workflow_version: int | None = None


def create_app(data_dir=None, port=4395, stop_token=None):
    data_dir = data_dir or os.environ.get('MODU_NODES_DATA_DIR') or str(ROOT / 'data')
    store = Store(data_dir)
    interrupted = store.mark_interrupted()
    engine = Engine(store)
    app = FastAPI(title='모두의리서치 노드', version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    from .agent import Agent, RULES, ACTION_LABEL
    agent = Agent(store, engine, check_assumptions)
    store.agent_mark_interrupted()
    app.state.store, app.state.engine = store, engine
    allowed_origins = {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}

    @app.middleware('http')
    async def guard(request: Request, call_next):
        owner = request.cookies.get(OWNER_COOKIE)
        csrf = request.cookies.get(CSRF_COOKIE)
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.url.path.startswith('/api/'):
            origin = request.headers.get('origin')
            if origin and origin not in allowed_origins:
                return JSONResponse({'detail': 'origin_rejected'}, 403)
            if not owner or not csrf or request.headers.get('x-csrf-token') != csrf:
                return JSONResponse({'detail': 'csrf_rejected'}, 403)
        request.state.owner = owner
        resp = await call_next(request)
        if not owner:
            resp.set_cookie(OWNER_COOKIE, secrets.token_hex(16), httponly=True, samesite='strict', max_age=10 * 365 * 86400)
        if not csrf:
            resp.set_cookie(CSRF_COOKIE, secrets.token_hex(16), httponly=False, samesite='strict', max_age=10 * 365 * 86400)
        return resp

    def owner(request):
        o = request.state.owner
        if not o:
            raise HTTPException(401, 'owner_cookie_missing')
        return o

    def parse(doc):
        try:
            return WorkflowDoc.model_validate(doc)
        except ValidationError as e:
            raise HTTPException(422, {'issues': [{'code': 'schema', 'severity': 'error', 'message': str(err['msg']),
                                                   'fix': '.'.join(str(x) for x in err['loc']), 'nodes': [], 'edge': None} for err in e.errors()]})

    @app.get('/api/health')
    def health():
        return {'ok': True, 'app': 'modu-research-nodes', 'version': VERSION, 'port': port,
                'data_dir_name': Path(data_dir).name, 'busy': engine.busy(), 'interrupted_on_start': interrupted}

    @app.post('/stop')
    def stop(request: Request):
        if not stop_token or not secrets.compare_digest(request.headers.get('x-stop-token', ''), stop_token):
            raise HTTPException(403, 'stop_token_rejected')
        import threading
        threading.Timer(0.3, lambda: os._exit(0)).start()
        return {'stopping': True, 'app': 'modu-research-nodes'}

    @app.get('/api/registry')
    def registry():
        return {'nodes': REGISTRY, 'perspectives': PERSPECTIVES, 'port_types': PORT_TYPES, 'kinds': KINDS}

    @app.get('/api/plan')
    def get_plan(perspectives: str = ''):
        sel = [p for p in perspectives.split(',') if p]
        try:
            return plan_workflow(sel)
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.post('/api/validate')
    def do_validate(body: dict):
        doc = parse(body.get('doc', {}))
        issues = validate(doc, check_assumptions)
        order = []
        if not blocking(issues):
            order = topo_order(doc)
        return {'issues': issues, 'order': order, 'runnable': not blocking(issues)}

    @app.get('/api/workflows')
    def list_wf(request: Request):
        return store.list_workflows(owner(request))

    @app.post('/api/workflows')
    def create_wf(body: SaveBody, request: Request):
        doc = parse(body.doc)
        wid, ver = store.save_workflow(owner(request), doc.model_dump(), note=body.note)
        return {'id': wid, 'version': ver}

    @app.put('/api/workflows/{wid}')
    def save_wf(wid: str, body: SaveBody, request: Request):
        doc = parse(body.doc)
        try:
            ver = store.save_workflow(owner(request), doc.model_dump(), wid, body.note)[1]
        except NotFound:
            raise HTTPException(404, 'workflow_not_found')
        return {'id': wid, 'version': ver}

    @app.get('/api/workflows/{wid}')
    def get_wf(wid: str, request: Request):
        try:
            wf = store.get_workflow(owner(request), wid)
        except NotFound:
            raise HTTPException(404, 'workflow_not_found')
        wf['runs'] = store.list_runs(owner(request), wid)
        return wf

    @app.post('/api/runs', status_code=201)
    def start_run(body: RunBody, request: Request):
        o = owner(request)
        doc = parse(body.doc)
        if not doc.cutoff:
            doc.cutoff = now()
        issues = validate(doc, check_assumptions)
        if blocking(issues):
            raise HTTPException(422, {'issues': issues})
        order = topo_order(doc)
        try:
            run_id = engine.start(o, doc.model_dump(), order, body.workflow_id, body.workflow_version)
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        return {'id': run_id, 'order': order}

    @app.get('/api/runs/{rid}')
    def get_run(rid: str, request: Request):
        try:
            run = store.get_run(owner(request), rid)
        except NotFound:
            raise HTTPException(404, 'run_not_found')
        t = now()
        for n in run['nodes']:
            n['stalled'] = False
            if n['status'] == 'running' and n['heartbeat_at']:
                n['stalled'] = (instant(t) - instant(n['heartbeat_at'])).total_seconds() > 10
        run['server_time'] = t
        return run

    @app.post('/api/runs/{rid}/cancel')
    def cancel(rid: str, request: Request):
        try:
            return {'status': store.request_cancel(owner(request), rid)}
        except NotFound:
            raise HTTPException(404, 'run_not_found')

    @app.get('/api/runs')
    def runs(request: Request, workflow_id: str | None = None):
        return store.list_runs(owner(request), workflow_id)

    @app.get('/api/packets/{pid}')
    def packet(pid: str, request: Request):
        try:
            return store.get_packet(pid, owner(request))
        except NotFound:
            raise HTTPException(404, 'packet_not_found')

    def facts_for(owner_id, run_id):
        """Facts from a run's N01 packets (provenance kept) or, if none, a fresh verified corpus."""
        from .nodes import _fact
        from .official import load_corpus
        facts, source = {}, ''
        if run_id:
            run = store.get_run(owner_id, run_id)
            for n in run['nodes']:
                if n['node_type'] == 'N01' and n['output_packet']:
                    for f in store.get_packet(n['output_packet'], owner_id)['payload']['facts']:
                        facts[f['fact_id']] = f
            source = f'실행 {run_id[:8]}의 N01 결과 {len(facts)}건'
        if not facts:
            c = load_corpus()
            for comp in c['companies']:
                doc = comp['documents'][0]
                for y in comp['years']:
                    for m in y['inputs']:
                        f = _fact(comp, doc, y, m)
                        facts[f['fact_id']] = f
            source = f'저장 공식 원문 재대조 {len(facts)}건'
        return facts, source

    @app.post('/api/numeric/check')
    def numeric_check(body: CheckBody, request: Request):
        if body.mode not in ('research', 'conservative'):
            raise HTTPException(422, 'mode')
        if len(body.text) > 20000:
            raise HTTPException(413, 'text_too_long')
        try:
            facts, source = facts_for(owner(request), body.run_id)
        except NotFound:
            raise HTTPException(404, 'run_not_found')
        r = numeric.analyze(body.text, facts, body.mode, question=body.question)
        r['facts_source'] = source
        r['fact_ids'] = sorted(facts)
        return r

    @app.post('/api/broker/scan')
    def broker_scan(request: Request):
        from . import broker
        try:
            import pymupdf  # noqa: F401
        except ImportError:
            raise HTTPException(503, 'PDF 읽기 모듈(PyMuPDF)이 설치되지 않았습니다. setup.cmd를 다시 실행하세요.')
        facts, src = facts_for(owner(request), None)
        facts = {**broker.filing_facts(), **facts}        # 다른 회사: 공시 API 연간 재무로 과거 열 대조
        reports, cands = broker.scan(facts)
        res = store.broker_upsert(owner(request), reports, cands)
        return {'folder': broker.broker_dir().name, 'reports': len(reports), 'candidates': len(cands), **res, 'facts_source': src}

    @app.get('/api/broker/reports')
    def broker_list():
        reps, cands = store.broker_reports()
        return {'reports': reps, 'candidates': cands}

    @app.post('/api/broker/review')
    def broker_review(body: ReviewBody, request: Request):
        o = owner(request)
        try:
            if body.file and body.action == 'approve_report':
                _, cands = store.broker_reports()
                ids = [c['id'] for c in cands if c['file'] == body.file and c['state'] == 'proposed']
                for i in ids:
                    store.broker_review(o, i, 'approve', note=body.note or '보고서 단위 일괄 승인')
                return {'approved': len(ids)}
            if body.action == 'edit':
                if body.value_mn is None or not re.fullmatch(r'-?\d+(\.\d+)?', body.value_mn.replace(',', '')):
                    raise ValueError('수정값은 백만원 단위 숫자로 입력하세요.')
                body.value_mn = body.value_mn.replace(',', '')
            return {'state': store.broker_review(o, body.id, body.action, body.value_mn, body.note)}
        except NotFound:
            raise HTTPException(404, 'candidate_not_found')
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.get('/api/broker/compare')
    def broker_compare():
        from .broker import stats
        reps, cands = store.broker_reports()
        cols = [(2026, 'revenue'), (2026, 'operatingProfit'), (2027, 'revenue'), (2027, 'operatingProfit')]
        rows = []
        for r in sorted(reps, key=lambda r: (r['report_date'], r['broker'])):
            mine = {(c['fiscal_year'], c['metric']): c for c in cands if c['file'] == r['file'] and c['state'] != 'stale'}
            cells = {}
            for fy, m in cols:
                c = mine.get((fy, m))
                cells[f'{fy}:{m}'] = None if not c else {'id': c['id'], 'value_mn': c['effective_value_mn'], 'state': c['state'],
                                                         'page': c['page'], 'quote': c['quote'], 'edited': bool(c.get('review_value_mn'))}
            rows.append({'file': r['file'], 'broker': r['broker'], 'report_date': r['report_date'], 'ticker': r.get('ticker'), 'title': r.get('title'),
                         'opinion': r.get('opinion'), 'target_price': r.get('target_price'), 'tp_quote': r.get('tp_quote'), 'tp_page': r.get('tp_page'),
                         'tp_prior': r.get('tp_prior'), 'tp_prior_quote': r.get('tp_prior_quote'), 'multiple': r.get('multiple'),
                         'multiple_quote': r.get('multiple_quote'), 'past_check': r.get('past_check'), 'status': r.get('status'),
                         'notes': r.get('notes', []), 'cells': cells})
        summary = {}
        for fy, m in cols:
            k = f'{fy}:{m}'
            vals_all = [x['cells'][k]['value_mn'] for x in rows if x['cells'][k] and x['cells'][k]['state'] in ('approved', 'proposed')]
            vals_ok = [x['cells'][k]['value_mn'] for x in rows if x['cells'][k] and x['cells'][k]['state'] == 'approved']
            summary[k] = {'all': stats(vals_all), 'approved': stats(vals_ok)}
        tps = [x['target_price'] for x in rows if x['target_price']]
        summary['target_price'] = {'all': stats(tps)}
        timeline = {}
        for x in rows:
            pts = timeline.setdefault(x['broker'], [])
            if x['tp_prior']:
                pts.append({'date': None, 'tp': x['tp_prior'], 'kind': 'prior_mention', 'note': f"{x['report_date']} 보고서에 언급된 이전 목표주가(날짜 미상)"})
            pts.append({'date': x['report_date'], 'tp': int(x['target_price']) if x['target_price'] else None, 'kind': 'report', 'file': x['file']})
        return {'columns': [f'{fy}:{m}' for fy, m in cols], 'rows': rows, 'summary': summary, 'timeline': timeline, 'companies': _broker_names({x['ticker'] for x in rows}),
                'notice': '증권사 외부 전망입니다. 여러 전망을 하나로 합치지 않고 나란히 보여 줍니다. 통계는 참고용이며 컨센서스가 아닙니다.'}

    web = ROOT / 'web'
    app.mount('/static', StaticFiles(directory=web), name='static')

    # ---- agent (rule-based self-correcting runner) -------------------------
    @app.get('/api/agent/rules')
    def agent_rules():
        return {'rules': RULES, 'labels': ACTION_LABEL}

    @app.post('/api/agent/runs', status_code=201)
    def agent_start(body: AgentBody, request: Request):
        o = owner(request)
        doc = parse(body.doc)
        if not 1 <= body.max_iters <= 6:
            raise HTTPException(422, 'max_iters')
        return {'id': agent.start(o, doc.model_dump(), body.goal, body.max_iters)}

    # ---- RAG over whole business reports (T1) -----------------------------
    rag_state = {'index': None, 'error': ''}
    rag_dir = os.environ.get('MODU_NODES_RAG_DIR') or os.path.join(data_dir, 'rag')
    rag_src = os.environ.get('MODU_NODES_DART_FULL') or str(ROOT.parent / '_sources' / 'dart_full')

    def rag_index(rebuild=False):
        from .rag.shared import get_index, RagUnavailable
        try:
            rag_state['index'] = get_index(data_dir, rebuild)
        except RagUnavailable as e:
            raise HTTPException(503, str(e))
        return rag_state['index']

    @app.get('/api/rag/status')
    def rag_status():
        try:
            idx = rag_index()
        except HTTPException as e:
            return {'ready': False, 'error': e.detail}
        m = idx.manifest
        return {'ready': True, 'chunks': idx.N, 'files': len(m['files']), 'companies': m['companies'], 'parser': m['parser'],
                'corpusHash': m['corpusHash'][:16], 'rejected': m['rejected'], 'vectors': idx.vectors is not None,
                'model': (idx.vec_meta or {}).get('model'),
                'receipts': sorted({(f['code'], f['rcpNo']) for f in m['files']})}

    @app.post('/api/rag/search')
    def rag_search(body: RagBody, request: Request):
        idx = rag_index()
        k = max(1, min(body.k, 30))
        r = idx.search(body.query[:300], company=body.company or None, k=k, mode=body.mode, synonyms=body.synonyms)
        store.agent_audit(owner(request), 'rag.search', (body.company or 'all'), {'query': body.query[:300], 'mode': r['mode'], 'hits': len(r['hits'])})
        return r

    @app.get('/api/rag/eval')
    def rag_eval(mode: str = 'auto'):
        from .rag.evaluate import run
        idx = rag_index()
        return {'with_synonyms': run(idx, mode=mode, synonyms=True), 'without_synonyms': run(idx, mode=mode, synonyms=False)}

    # ---- DART OpenAPI (XBRL-based) financial statements -------------------
    @app.get('/api/xbrl/status')
    def xbrl_status():
        from .xbrl import api_key, cache_dir, CORP
        d = cache_dir(data_dir)
        return {'key_configured': bool(api_key()), 'companies': CORP, 'cached': sorted(os.listdir(d))}

    @app.post('/api/xbrl/fetch')
    def xbrl_fetch(body: XbrlBody, request: Request):
        from .xbrl import fetch, parse, crosscheck, XbrlError
        o = owner(request)
        try:
            data, info = fetch(data_dir, body.company, body.year, refresh=body.refresh)
        except XbrlError as e:
            store.agent_audit(o, 'xbrl.fetch_failed', body.company, {'year': body.year, 'error': str(e)[:200]})
            raise HTTPException(502, str(e))
        facts = parse(data, body.company, body.year)
        cells, src = facts_for(o, None)
        cc = crosscheck(facts, cells)
        store.agent_audit(o, 'xbrl.fetch', body.company, {'year': body.year, 'cached': info['cached'], 'sha256': info['sha256'], 'facts': len(facts)})
        return {'company': body.company, 'year': body.year, 'cache': info, 'facts': facts, 'crosscheck': cc,
                'crosscheck_source': src, 'rcept_no': (facts[0]['rcept_no'] if facts else None),
                'summary': {'facts': len(facts), 'compared': len(cc), 'matched': sum(1 for r in cc if r['match'])}}

    @app.post('/api/agent/assemble')
    def agent_assemble(body: AssembleBody, request: Request):
        from .assembler import assemble
        o = owner(request)
        r = assemble(body.question, body.pick, body.cutoff)
        if r['doc']:
            d = WorkflowDoc.model_validate(r['doc'])
            r['issues'] = [i for i in validate(d, check_assumptions) if i['severity'] == 'error']
        store.agent_audit(o, 'agent.assemble', r['status'], {
            'question': r['question'][:300], 'status': r['status'], 'targets': [t['type'] for t in r['targets']],
            'gaps': [g['id'] for g in r['gaps']], 'signature': r.get('signature', ''), 'picked': bool(body.pick)})
        return r

    @app.get('/api/universe')
    def api_universe(snapshot: str = ''):
        """C: 시장 근거 지도 — 사본의 기업 × 자료 유무(개수·최근 날짜). 행은 읽지 않고 개수 표만 읽는다."""
        from .market import universe, SnapshotError
        try:
            return universe(snapshot)
        except SnapshotError as e:
            raise HTTPException(409, {'code': e.code, 'message': str(e)})

    @app.get('/api/universe/gaps.csv')
    def api_universe_gaps(snapshot: str = ''):
        """빈칸 목록 — 어떤 회사에 어떤 자료가 없는지(수집 담당자에게 넘길 표)."""
        import csv, io
        from fastapi.responses import Response
        from .market import universe, SnapshotError
        try:
            u = universe(snapshot)
        except SnapshotError as e:
            raise HTTPException(409, {'code': e.code, 'message': str(e)})
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['종목코드', '회사', '시장', '빠진 자료', '관련 노드', '사본'])
        for c in u['companies']:
            for col in u['columns']:
                if not c['cover'][col['key']]['n'] and col['key'] not in ('price_other', 'peer_auto'):
                    w.writerow([c['ticker'], c['name'], c['market'], col['label'], ' '.join(col['nodes']), u['snapshot']])
        name = f"근거지도_빈칸_{u['snapshot'][:15]}.csv"
        from urllib.parse import quote
        return Response('\ufeff' + buf.getvalue(), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})

    @app.get('/api/agent/assemble/map')
    def agent_assemble_map(request: Request):
        from .assembler import map_from_audit
        return map_from_audit(store.audit_details(owner(request), 'agent.assemble'))

    @app.post('/api/agent/plan')
    def agent_plan(body: PlanBody, request: Request):
        from .planner import plan
        o = owner(request)
        r = plan(body.question, body.persona, body.use_model)
        store.agent_audit(o, 'agent.plan', r['example_id'], {'question': r['question'], 'method': r['method'], 'model_note': r['model_note']})
        return r

    @app.get('/api/agent/objection-fields')
    def objection_fields(run_id: str, node_id: str, request: Request):
        from .objection import fields_for, KINDS
        try:
            run = store.get_run(owner(request), run_id)
        except NotFound:
            raise HTTPException(404, 'run_not_found')
        node = next((n for n in run['doc']['nodes'] if n['id'] == node_id), None)
        if not node:
            raise HTTPException(404, 'node_not_found')
        reports = store.broker_reports()[0] if node['type'] == 'T04' else None
        return {'node': node_id, 'type': node['type'], 'kind': KINDS.get(node['type']), 'fields': fields_for(node, reports), 'cutoff': run['doc'].get('cutoff')}

    @app.post('/api/agent/objections', status_code=201)
    def objection_create(body: ObjectionBody, request: Request):
        from .objection import apply, ObjectionError, KINDS, new_id
        o = owner(request)
        if len(body.reason.strip()) < 5:
            raise HTTPException(422, '이의 사유를 5자 이상 적어 주세요.')
        try:
            run = store.get_run(o, body.run_id)
        except NotFound:
            raise HTTPException(404, 'run_not_found')
        if run['status'] in ('waiting', 'running'):
            raise HTTPException(409, '실행이 끝난 뒤 이의를 제기하세요.')
        try:
            new_doc, change = apply(run['doc'], body.node_id, body.field, body.value, store.broker_reports()[0])
        except ObjectionError as e:
            raise HTTPException(422, str(e))
        node_type = next(n['type'] for n in run['doc']['nodes'] if n['id'] == body.node_id)
        new_doc['name'] = (run['doc'].get('name') or '워크플로') + ' · 이의 재심의'
        oid = new_id()
        aid = agent.start(o, new_doc, f"이의 재심의: {change['label']} {change['before']} → {change['after']}")
        store.objection_save(o, oid, {'base_run': body.run_id, 'node': body.node_id, 'node_type': node_type, 'kind': KINDS[node_type],
                                      'field': body.field, 'change': change, 'reason': body.reason.strip(), 'agent_run': aid})
        return {'id': oid, 'agent_run': aid}

    @app.get('/api/agent/objections/{oid}')
    def objection_get(oid: str, request: Request):
        from .objection import compare
        o = owner(request)
        try:
            ob = store.objection_get(o, oid)
        except NotFound:
            raise HTTPException(404, 'objection_not_found')
        a = store.agent_get(o, ob['agent_run'])
        ob['agent'] = {k: a.get(k) for k in ('status', 'note', 'iteration', 'max_iters', 'changes', 'asks', 'accepted', 'summary', 'final_run', 'steps', 'runs', 'doc_final')}
        if a['status'] != 'running' and a.get('final_run'):
            ob['comparison'] = compare(store, o, ob['base_run'], a['final_run'])
        return ob

    @app.post('/api/agent/gate')
    def agent_gate(body: GateBody, request: Request):
        from .gate import context, check
        if len(body.text) > 20000:
            raise HTTPException(413, 'text_too_long')
        try:
            _, _, facts, externals, derived = context(store, owner(request), body.run_id)
        except NotFound:
            raise HTTPException(404, 'run_not_found')
        return check(body.text, facts, externals, derived)

    @app.get('/api/agent/runs/{aid}')
    def agent_get(aid: str, request: Request):
        try:
            return store.agent_get(owner(request), aid)
        except NotFound:
            raise HTTPException(404, 'agent_run_not_found')

    # ---------------------------------------------------------------- v0.15 쉬운 화면
    @app.get('/api/easy/cards')
    def easy_cards(request: Request, company: str = '005930'):
        from .easy import CARDS, card_status
        from .market import universe, SnapshotError
        cover, name = None, None
        try:
            u = universe()
            c = next((x for x in u['companies'] if x['ticker'] == company), None)
            cover, name = (c['cover'], c['name']) if c else ({}, None)
        except SnapshotError:
            pass
        out = []
        ledger = ledger_tickers()
        reported = reported_tickers()
        for cd in CARDS:
            ok, why = card_status(cd, company, cover, ledger, reported)
            out.append({k: cd[k] for k in ('id', 'title', 'sub', 'group', 'kind', 'doors', 'next')} | {'ok': ok, 'why': why})
        from .attention import CARD as _ATC    # v0.27 관심 체온계 — 이 모듈이 직접 답하는 카드
        ok, why = card_status(_ATC, company, cover, ledger)
        out.append({k: _ATC[k] for k in ('id', 'title', 'sub', 'group', 'kind', 'doors', 'next', 'view')} | {'ok': ok, 'why': why})
        from .reaction import CARD as _RXC     # v0.25 공시 반응 사전 — 이 모듈이 직접 답하는 카드
        ok, why = card_status(_RXC, company, cover, ledger)
        out.append({k: _RXC[k] for k in ('id', 'title', 'sub', 'group', 'kind', 'doors', 'next', 'view')} | {'ok': ok, 'why': why})
        from .easy import GROUPS, DOORS, SHORT as _SHORT
        for c in out:
            c['short'] = _SHORT.get(c['id'])
        from .mycards import easy_cards as _my_cards           # v0.36 내가 만든 질문 — 저장한 카드가 있을 때만 묶음이 생김
        _mine, _mg = _my_cards(store, request.state.owner, company)
        return {'company': company, 'name': name, 'cards': out + _mine, 'groups': GROUPS + _mg, 'doors': DOORS}

    def reported_tickers():
        """v0.37.6: 보고서를 하나라도 받아 둔 종목(승인 여부와 무관)."""
        from .broker import broker_dir, load_manifest, report_ticker
        reps, _ = store.broker_reports()
        man = load_manifest(broker_dir())
        return {r.get('ticker') or report_ticker(man.get(r['file'])) for r in reps} - {None}

    def ledger_tickers():
        from .broker import broker_dir, load_manifest, report_ticker
        reps, cands = store.broker_reports()
        man = load_manifest(broker_dir())
        ok_files = {c['file'] for c in cands if c['state'] == 'approved'}
        return {r.get('ticker') or report_ticker(man.get(r['file'])) for r in reps if r['file'] in ok_files} - {None}

    def ledger_reference(ticker, fy, metric):
        """모두의 가정 값 검사용 참고값: 승인된 전망의 최신 집계 중앙값(없으면 None)."""
        from .broker import broker_dir, load_manifest, report_ticker
        from . import forecasts as FC
        reps, cands = store.broker_reports()
        man = load_manifest(broker_dir())
        files = {r['file'] for r in reps if (r.get('ticker') or report_ticker(man.get(r['file']))) == ticker}
        fs = [{'broker': c['broker'], 'report_date': c['report_date'], 'metric': c['metric'], 'fiscal_year': c['fiscal_year'], 'value': c['effective_value_mn']}
              for c in cands if c['file'] in files and c['state'] == 'approved']
        tr = FC.trend(fs, metric, fy)
        return tr['latest']['median'] if tr else None

    # ---- 모두의 가정 (v0.18 C): 먼저 내 가정 → 그다음 분포(5명 이상), 결론은 받지 않음 ----------------
    @app.get('/api/crowd/{ticker}/{fy}/{metric}')
    def crowd_get(ticker: str, fy: int, metric: str, request: Request):
        from . import forecasts as FC
        if metric not in FC.METRICS:
            raise HTTPException(422, '매출액·영업이익만 있어요.')
        o = owner(request)
        mine = store.crowd_mine(o, ticker, fy, metric)
        out = {'ticker': ticker, 'fiscal_year': fy, 'metric': metric, 'metric_label': FC.METRICS[metric], 'min_n': FC.CROWD_MIN,
               'mine': mine, 'unlocked': bool(mine),
               'rule': '먼저 내 가정을 적은 사람만 다른 사람들의 분포를 봐요. 5명 이상 모였을 때 중앙값과 가운데 절반 범위만 보여 주고, 한 사람의 값은 보여 주지 않아요.'}
        if not mine:
            out['n'] = len(store.crowd_values(ticker, fy, metric))
            return out
        out['stats'] = FC.crowd_stats(store.crowd_values(ticker, fy, metric))
        out['monthly'] = [{'period': p, **FC.crowd_stats(v)} for p, v in store.crowd_monthly(ticker, fy, metric).items()]
        return out

    @app.post('/api/crowd/submit')
    def crowd_submit(body: CrowdBody, request: Request):
        from . import forecasts as FC
        from decimal import Decimal
        if not (2024 <= body.fiscal_year <= 2035):
            raise HTTPException(422, '연도를 확인해 주세요.')
        value_mn = str((Decimal(str(body.value_jo)) * Decimal(1000000)).quantize(Decimal(1)))
        err = FC.check_value(body.metric, value_mn, ledger_reference(body.ticker, body.fiscal_year, body.metric))
        if err:
            raise HTTPException(422, err)
        r = store.crowd_submit(owner(request), body.ticker, body.fiscal_year, body.metric, value_mn)
        return {'ok': True, 'value_mn': value_mn, **r}

    # ---- 증권사 보고서 받은 편지함 (v0.18 T2): 내려받은 PDF를 inbox에 넣으면 등록 도우미가 채워 준다 ----------
    @app.get('/api/broker/inbox')
    def broker_inbox():
        from . import broker
        return {'folder': str(broker.inbox_dir()), 'items': broker.inbox_items()}

    @app.post('/api/broker/register')
    def broker_register(body: RegisterBody, request: Request):
        from . import broker
        try:
            rec = broker.register(body.model_dump())
        except ValueError as e:
            raise HTTPException(422, str(e))
        with store.connect() as c:
            store.audit(c, owner(request), 'broker.register', rec['파일명'], {'ticker': body.ticker, 'broker': body.broker, 'date': body.report_date})
        return {'ok': True, 'record': rec}

    @app.post('/api/easy/run', status_code=201)
    def easy_run(body: EasyRunBody, request: Request):
        from .easy import plan, CARD
        o = owner(request)
        if body.card.startswith('my:'):                         # v0.36 내 질문 카드
            from .mycards import plan_doc as _my_plan
            try:
                doc = parse(_my_plan(store, o, body.card, body.company, body.cutoff))
            except LookupError:
                raise HTTPException(404, 'card_not_found')
            except ValueError as e:
                raise HTTPException(422, str(e))
        elif body.card not in CARD:
            raise HTTPException(404, 'card_not_found')
        else:
            doc = parse(plan(body.card, body.company, body.cutoff, body.rcept_no.strip()) if body.card == 'filing' else plan(body.card, body.company, body.cutoff))
        if not doc.cutoff:
            doc.cutoff = now()
        issues = validate(doc, check_assumptions)
        if blocking(issues):
            raise HTTPException(422, {'issues': issues})
        try:
            run_id = engine.start(o, doc.model_dump(), topo_order(doc))
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        store.agent_audit(o, 'easy.run', body.card, {'company': body.company, 'cutoff': doc.cutoff})
        return {'id': run_id}

    @app.get('/api/easy/answer/{rid}')
    def easy_answer(rid: str, request: Request):
        from .easy import answer
        o = owner(request)
        try:
            run = store.get_run(o, rid)
        except NotFound:
            raise HTTPException(404, 'run_not_found')
        from .market import company_name
        from .autocheck import seen_info                 # v0.38 T2-4d (J23)
        return answer(run, lambda pid: store.get_packet(pid, o), company_name, seen=lambda no: seen_info(store, no))

    @app.get('/api/easy/repairs/{rid}')
    def easy_repairs(rid: str, request: Request):
        """C: 막힌 곳별 대체안 (적용은 사람이 고른 것만)."""
        from .repair import suggest
        o = owner(request)
        try:
            run = store.get_run(o, rid)
        except NotFound:
            raise HTTPException(404, 'run_not_found')
        if run['status'] in ('waiting', 'queued', 'running'):
            return {'proposals': []}
        return {'proposals': [{k: v for k, v in p.items() if k != 'patch'} for p in suggest(run, lambda pid: store.get_packet(pid, o))]}

    @app.post('/api/easy/repair', status_code=201)
    def easy_repair(body: RepairBody, request: Request):
        from .repair import suggest, apply
        o = owner(request)
        try:
            run = store.get_run(o, body.run_id)
        except NotFound:
            raise HTTPException(404, 'run_not_found')
        props = suggest(run, lambda pid: store.get_packet(pid, o))
        try:
            nd = apply(run['doc'], props, set(body.ids))
        except ValueError as e:
            raise HTTPException(422, str(e))
        nd['meta']['repaired_from'] = body.run_id
        doc = parse(nd)
        issues = validate(doc, check_assumptions)
        if blocking(issues):
            raise HTTPException(422, {'issues': issues})
        try:
            new_id = engine.start(o, doc.model_dump(), topo_order(doc))
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        store.agent_audit(o, 'easy.repair', ','.join(sorted(body.ids))[:200],
                          {'from': body.run_id, 'to': new_id, 'codes': [p['id'].split('-')[0] for p in props if p['id'] in body.ids],
                           'downgrade': any(p['downgrade'] for p in props if p['id'] in body.ids)})
        return {'id': new_id}

    @app.get('/api/easy/receipt/{rid}')
    def easy_receipt(rid: str, request: Request):
        from .easy import receipt
        o = owner(request)
        try:
            run = store.get_run(o, rid)
        except NotFound:
            raise HTTPException(404, 'run_not_found')
        if run['status'] in ('waiting', 'queued', 'running'):
            raise HTTPException(409, '실행이 끝난 뒤에 근거 확인서를 만들 수 있습니다.')
        return receipt(run, lambda pid: store.get_packet(pid, o))

    @app.post('/api/easy/verify')
    def easy_verify(body: dict, request: Request):
        from .easy import verify
        o = owner(request)
        rc = body.get('receipt') or {}
        need = ('format', 'cutoff', 'chain_digest', 'results', 'receipt_id', 'chain')
        if any(k not in rc for k in need) or rc.get('format') != 'modu-research-receipt/1':
            raise HTTPException(422, '모두의리서치 근거 확인서 파일이 아닙니다.')

        def rerun(doc):
            d = parse(doc)
            if blocking(validate(d, check_assumptions)):
                return {}
            try:
                rid = engine.start(o, d.model_dump(), topo_order(d), background=False)
            except RuntimeError as e:
                raise HTTPException(409, str(e))
            run = store.get_run(o, rid)
            return {n['node_id']: (store.get_packet(n['output_packet'], o)['header']['payload_digest'] if n['output_packet'] else None) for n in run['nodes']}
        r = verify(rc, rerun)
        store.agent_audit(o, 'easy.verify', 'ok' if r['ok'] else 'mismatch', {'receipt': rc.get('receipt_id', '')[:16], 'matched': r.get('matched')})
        return r

    def page(name):
        """v0.23.3: 화면 HTML 안의 /static/*.css·js 주소에 파일 수정 시각을 붙인다 → 화면을 바꾸면 브라우저가 예전 디자인 파일을 쓰지 않는다."""
        from fastapi.responses import HTMLResponse
        html = (web / name).read_text(encoding='utf-8')

        def ver(m):
            f = web / m.group(2)
            return f'{m.group(1)}{m.group(2)}?v={int(f.stat().st_mtime)}' if f.is_file() else m.group(0)
        html = re.sub(r'(/static/)([\w.-]+\.(?:css|js))', ver, html)
        return HTMLResponse(html, headers={'Cache-Control': 'no-store'})

    @app.get('/expert')
    def expert_page():
        return page('index.html')

    @app.get('/')
    def index():
        return page('easy.html')

    from .reaction_api import register as _reaction_register   # v0.25
    _reaction_register(app)
    from .attention_api import register as _attention_register   # v0.27
    _attention_register(app)
    from .guide_api import register as _guide_register         # v0.26 AI 길잡이(기본 꺼짐)
    _guide_register(app, store, owner)
    from .share_api import register as _share_register       # v0.32 공유·가설 일지·배우는 길
    _share_register(app, store, owner)
    from .journal_api import register as _journal_register
    _journal_register(app, store, owner, now)
    from .mycards import register as _mycards_register         # v0.36 내 질문 카드
    _mycards_register(app, store, owner, now, parse)
    from .watch_api import register as _watch_register         # v0.38 T1 관심 종목
    _watch_register(app, store, owner, now)
    from .watch_api import register_filings as _filings_register
    _filings_register(app, store, owner)
    from .watch_api import register_autocheck as _autocheck_register   # v0.38 T2-1 공시 자동 확인(API만; 일정은 __main__에서)
    _autocheck_register(app, store, owner)
    from .research_data_api import register as _rd_register     # v0.39.2 연구용 데이터(시세 보여 주기·컨센서스, 스위치)
    _rd_register(app, store)
    from .report_draft_api import register as _draft_register   # v0.39.4 근거 고정 보고서 초안
    _draft_register(app, store, owner)
    return app


def _broker_names(tickers):
    """v0.35: 종목코드 → 회사 이름(사본 기준). 사본이 없으면 빈 사전 — 화면은 코드만 보여 준다."""
    try:
        from .market import resolve, load_manifest, companies
        root = resolve(''); allc = companies(root, load_manifest(root))
        return {t: (allc.get(t) or {}).get('name') for t in tickers if t}
    except Exception:
        return {}
