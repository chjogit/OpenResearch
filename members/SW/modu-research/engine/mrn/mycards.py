"""v0.36 내 질문 카드 — 전문가 모드에서 짠 흐름을 「회사만 비운 조사 방법」으로 저장해 쉬운 화면의 질문 카드로 쓴다.

복잡해지지 않게 지키는 것
- 쉬운 화면에는 새 낱말·새 단추가 없다. 저장한 카드가 있을 때만 「내가 만든 질문」 묶음이 생기고, 카드는 기존 카드와 똑같이 눌러 쓴다.
- 회사는 고른 회사로 바꿔 끼운다. 회사마다 값이 다른 노드(T03 가치평가 가정, T04 특정 보고서)는 카드로 저장하지 않는다.
- 공유는 파일 묶음(조사 방법 + 그 방법으로 한 번 계산한 근거 확인서). 순위·적중률·추천은 없다.
- 새 표 하나(my_cards)만 더한다. 지우지 않고 숨긴다.
"""
import hashlib
import json
import secrets

from .specs import SPECS

FORMAT = 'modu-research-card/1'
PH = '{{company}}'
NOT_PORTABLE = {'T03': '가치평가 가정(주식 수·현금흐름)은 회사마다 달라요', 'T04': '특정 증권사 보고서를 고른 노드예요'}
CLEAR_FIELDS = {'N17': ['extra_shares']}            # 회사마다 다른 값 — 카드에서는 비운다
KINDS = ('사실', '관계', '가정')
MAX_NODES, TITLE_MAX, SUB_MAX = 40, 60, 120
GROUP = {'id': 'mine', 'title': '내가 만든 질문', 'sub': '전문가 모드에서 저장한 조사 방법 — 고른 회사로 바꿔 계산해요'}
NOT_THIS = '조사 방법과 그 방법으로 한 번 계산한 근거 확인서입니다. 결론·종목 추천·적중률이 아닙니다.'

DDL = """CREATE TABLE IF NOT EXISTS my_cards(
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, title TEXT NOT NULL, sub TEXT NOT NULL, kind TEXT NOT NULL,
  template TEXT NOT NULL, origin TEXT NOT NULL, receipt TEXT, source_run TEXT, created_at TEXT NOT NULL, hidden INTEGER NOT NULL DEFAULT 0)"""


def ensure(store):
    with store.connect() as c:
        c.execute(DDL)


def _canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(template):
    return hashlib.sha256(_canon(template).encode()).hexdigest()


def company_fields(node_type):
    """이 노드에서 회사를 정하는 칸: [(키, 'one'|'many', 허용 목록 또는 None)]."""
    sc = SPECS[node_type].get('config_schema', {})
    out = []
    for k, f in sc.items():
        if k == 'company' and f.get('type') in ('company', 'enum'):
            out.append((k, 'one', list(f['options']) if f.get('type') == 'enum' else None))
        elif k == 'companies' and f.get('type') == 'multi':
            out.append((k, 'many', list(f.get('options') or [])))
    return out


def to_template(doc):
    """흐름 → 조사 방법. (template, problems) — problems가 있으면 저장하지 않는다."""
    nodes = doc.get('nodes') or []
    probs = []
    if not nodes:
        probs.append('캔버스가 비어 있어요.')
    if len(nodes) > MAX_NODES:
        probs.append(f'노드가 {MAX_NODES}개를 넘어요.')
    out, slots = [], 0
    for n in nodes:
        t = n.get('type')
        if t not in SPECS:
            probs.append(f'알 수 없는 노드 {t}')
            continue
        if t in NOT_PORTABLE:
            probs.append(f'{t} {SPECS[t]["display_name"]}: {NOT_PORTABLE[t]}. 이 노드를 빼고 저장하거나 전문가 모드에서만 쓰세요.')
            continue
        cfg = json.loads(json.dumps(n.get('config') or {}))
        for k, mode, _ in company_fields(t):
            if mode == 'one':
                cfg[k] = PH
                slots += 1
            elif cfg.get(k):
                cfg[k] = [PH]
                slots += 1
        for k in CLEAR_FIELDS.get(t, []):
            cfg.pop(k, None)
        out.append({'id': n['id'], 'type': t, 'config': cfg, 'x': n.get('x', 0), 'y': n.get('y', 0)})
    if nodes and not slots:
        probs.append('회사를 고르는 노드가 없어 종목을 바꿔 끼울 수 없어요(가격·수급·공시 같은 자료 노드가 하나는 있어야 해요).')
    ids = {n['id'] for n in nodes}
    edges = [{k: e[k] for k in ('from_node', 'from_port', 'to_node', 'to_port')} for e in doc.get('edges') or []]
    if any(e['from_node'] not in ids or e['to_node'] not in ids for e in edges):
        probs.append('끊어진 연결선이 있어요.')
    keep = {n['id'] for n in out}
    edges = [e for e in edges if e['from_node'] in keep and e['to_node'] in keep]
    return {'nodes': out, 'edges': edges}, probs


def fill(template, company):
    """조사 방법 + 회사 → 흐름 노드·연결선. 이 회사로 못 쓰는 노드가 있으면 ValueError(이유)."""
    if not company or not str(company).strip():
        raise ValueError('회사를 골라 주세요.')
    from .specs import COMPANIES as _BASE
    if any(n['type'] == 'T01' for n in template['nodes']) and company not in _BASE:   # v0.37.7: 원문 묶음(T01)은 두 기준 회사 것 — 다른 회사에 끼우면 엉뚱한 회사 자료가 섞임
        raise ValueError(f'이 카드의 「{SPECS["T01"]["display_name"]}」 단계는 원문을 가진 두 회사(삼성전자·SK하이닉스)만 돼요.')
    nodes = []
    for n in template['nodes']:
        cfg = json.loads(json.dumps(n.get('config') or {}))
        for k, mode, opts in company_fields(n['type']):
            if mode == 'one' and cfg.get(k) == PH:
                if opts and company not in opts:
                    raise ValueError(f'이 카드의 「{SPECS[n["type"]]["display_name"]}」 단계는 원문을 가진 두 회사(삼성전자·SK하이닉스)만 돼요.')
                cfg[k] = company
            elif mode == 'many' and cfg.get(k) == [PH]:
                if opts and company not in opts:
                    raise ValueError(f'이 카드의 「{SPECS[n["type"]]["display_name"]}」 단계는 원문을 가진 두 회사(삼성전자·SK하이닉스)만 돼요.')
                cfg[k] = [company]
        nodes.append({**n, 'config': cfg})
    return nodes, [dict(e) for e in template['edges']]


def outputs(template):
    return [n['id'] for n in template['nodes'] if n['type'].startswith('N')]


# ---------------------------------------------------------------- 저장소
def _row(r):
    tpl = json.loads(r['template'])
    return {'id': r['id'], 'title': r['title'], 'sub': r['sub'], 'kind': r['kind'], 'origin': r['origin'], 'created_at': r['created_at'],
            'node_types': [n['type'] for n in tpl['nodes']], 'template': tpl, 'has_receipt': bool(r['receipt']), 'source_run': r['source_run'],
            'receipt': json.loads(r['receipt']) if r['receipt'] else None}


def list_cards(store, owner):
    if not owner:
        return []
    ensure(store)
    with store.connect() as c:
        return [_row(r) for r in c.execute('SELECT * FROM my_cards WHERE owner_id=? AND hidden=0 ORDER BY created_at', (owner,))]


def get_card(store, owner, cid):
    ensure(store)
    with store.connect() as c:
        r = c.execute('SELECT * FROM my_cards WHERE id=? AND owner_id=? AND hidden=0', (cid, owner)).fetchone()
    if not r:
        raise LookupError(cid)
    return _row(r)


def _clean(title, sub, kind):
    title, sub = (title or '').strip(), (sub or '').strip()
    if not title:
        raise ValueError('카드 제목을 적어 주세요.')
    if len(title) > TITLE_MAX or len(sub) > SUB_MAX:
        raise ValueError(f'제목은 {TITLE_MAX}자, 설명은 {SUB_MAX}자까지예요.')
    if kind not in KINDS:
        raise ValueError('종류는 사실·관계·가정 중 하나예요.')
    from .guide import BANNED, FLOW_WORDS          # AI 길잡이와 같은 표현 규칙(수급 용어는 예외)
    m = BANNED.search(FLOW_WORDS.sub('', title + ' ' + sub))
    if m:
        raise ValueError(f'카드 이름에 판단 표현이 있어요(「{m.group(0)}」). 결론이 아니라 묻는 말로 적어 주세요.')
    return title, sub, kind


def save(store, owner, template, title, sub, kind, origin, at, receipt=None, source_run=None):
    title, sub, kind = _clean(title, sub, kind)
    ensure(store)
    cid = secrets.token_hex(6)
    with store.lock, store.connect() as c:
        if c.execute('SELECT 1 FROM my_cards WHERE owner_id=? AND hidden=0 AND title=? AND template=?', (owner, title, _canon(template))).fetchone():
            raise ValueError('같은 이름·같은 단계의 카드가 이미 있어요.')
        c.execute('INSERT INTO my_cards VALUES(?,?,?,?,?,?,?,?,?,?,0)',
                  (cid, owner, title, sub, kind, _canon(template), origin, _canon(receipt) if receipt else None, source_run, at))
        store.audit(c, owner, 'mycard.' + origin, cid, {'nodes': len(template['nodes']), 'receipt': bool(receipt)})
    return cid


def hide(store, owner, cid):
    ensure(store)
    with store.lock, store.connect() as c:
        n = c.execute('UPDATE my_cards SET hidden=1 WHERE id=? AND owner_id=?', (cid, owner)).rowcount
        if not n:
            raise LookupError(cid)
        store.audit(c, owner, 'mycard.hide', cid, {})


# ---------------------------------------------------------------- 쉬운 화면 연결
def meta_card(card):
    return {'title': card['title'], 'outputs': outputs(card['template']), 'group': 'mine', 'kind': card['kind'], 'next': [],
            'expert': ['전문가 모드에서 이 카드의 단계를 보고 바꾸기 — 바꾼 뒤 다시 「내 질문 카드」로 저장']}


def easy_cards(store, owner, company):
    """쉬운 화면 카드 목록에 덧붙일 것: (cards, groups). 카드가 없으면 아무것도 늘지 않는다."""
    out = []
    for cd in list_cards(store, owner):
        try:
            fill(cd['template'], company)
            ok, why = True, ''
        except ValueError as e:
            ok, why = False, str(e)
        out.append({'id': 'my:' + cd['id'], 'title': cd['title'], 'sub': cd['sub'] or f"직접 만든 조사 방법 · 단계 {len(cd['template']['nodes'])}개",
                    'group': 'mine', 'kind': cd['kind'], 'doors': ['ask', 'test', 'check'], 'next': [], 'ok': ok, 'why': why, 'mine': True})
    return out, ([GROUP] if out else [])


def plan_doc(store, owner, card_id, company, cutoff=''):
    cd = get_card(store, owner, card_id.split(':', 1)[1])
    nodes, edges = fill(cd['template'], company)
    name = f"{cd['title']} — {company}"
    return {'name': name[:100], 'cutoff': cutoff or '', 'nodes': nodes, 'edges': edges,
            'meta': {'card': card_id, 'company': company, 'ui': 'easy', 'my_card': meta_card(cd)}}


# ---------------------------------------------------------------- 묶음 파일 (T3 공유)
def bundle(card, receipt=None):
    return {'format': FORMAT, 'title': card['title'], 'sub': card['sub'], 'kind': card['kind'], 'template': card['template'],
            'template_digest': digest(card['template']), 'node_types': [n['type'] for n in card['template']['nodes']],
            'receipt': receipt, 'not_this': NOT_THIS,
            'how_to_use': '모두의리서치 전문가 모드 「내 질문 카드」 → 「받은 묶음 가져오기」에 이 파일을 넣으면 쉬운 화면 「내가 만든 질문」에 카드가 생깁니다. '
                          '들어 있는 근거 확인서는 같은 사본에서 다시 계산해 같은 결과가 나오는지 확인할 수 있습니다.'}


def check_bundle(b):
    """받은 묶음 검사 → template. 문제가 있으면 ValueError."""
    if not isinstance(b, dict) or b.get('format') != FORMAT:
        raise ValueError('모두의리서치 질문 카드 묶음 파일이 아닙니다.')
    tpl = b.get('template')
    if not isinstance(tpl, dict) or not isinstance(tpl.get('nodes'), list) or not isinstance(tpl.get('edges'), list):
        raise ValueError('묶음 안에 조사 방법이 없습니다.')
    if digest(tpl) != b.get('template_digest'):
        raise ValueError('조사 방법이 지문(해시)과 다릅니다 — 파일이 고쳐졌을 수 있어요.')
    if len(tpl['nodes']) > MAX_NODES:
        raise ValueError(f'노드가 {MAX_NODES}개를 넘어요.')
    for n in tpl['nodes']:
        if n.get('type') not in SPECS:
            raise ValueError(f'이 앱에 없는 노드가 있어요({n.get("type")}). 앱 버전이 다를 수 있어요.')
        if n['type'] in NOT_PORTABLE:
            raise ValueError(f'{n["type"]}는 카드에 넣을 수 없는 노드예요.')
    if not any(cfg_has_ph(n) for n in tpl['nodes']):
        raise ValueError('회사를 바꿔 끼울 자리가 없는 묶음이에요.')
    rc = b.get('receipt')
    if rc is not None and (not isinstance(rc, dict) or rc.get('format') != 'modu-research-receipt/1'):
        raise ValueError('묶음 안의 근거 확인서 형식이 맞지 않습니다.')
    return tpl


def cfg_has_ph(n):
    cfg = n.get('config') or {}
    return any(v == PH or v == [PH] for v in cfg.values())


# ---------------------------------------------------------------- API
def register(app, store, owner, now, parse):
    from fastapi import HTTPException, Request
    from pydantic import BaseModel
    from .workflow import validate, blocking
    from .nodes import check_assumptions

    class CardIn(BaseModel):
        doc: dict
        title: str
        sub: str = ''
        kind: str = '사실'
        source_run: str | None = None

    class ImportIn(BaseModel):
        bundle: dict

    def try_run(template):
        """회사 하나를 넣어 실행 전 검사까지 통과하는지(통과 못 하면 카드로 만들지 않음)."""
        for co in ('005930', '000660'):
            try:
                nodes, edges = fill(template, co)
            except ValueError:
                continue
            d = parse({'name': 'card-check', 'cutoff': '', 'nodes': nodes, 'edges': edges, 'meta': {}})
            iss = blocking(validate(d, check_assumptions))
            if iss:
                raise HTTPException(422, {'issues': iss, 'message': '이 흐름은 실행 전 검사를 통과하지 못해요. 「검증」으로 먼저 고쳐 주세요.'})
            return

    @app.get('/api/mycards')
    def my_list(request: Request):
        o = owner(request)
        return {'cards': [{k: v for k, v in c.items() if k not in ('template', 'receipt')} for c in list_cards(store, o)]}

    @app.post('/api/mycards', status_code=201)
    def my_save(body: CardIn, request: Request):
        o = owner(request)
        tpl, probs = to_template(body.doc)
        if probs:
            raise HTTPException(422, {'problems': probs, 'message': probs[0]})
        try_run(tpl)
        src = None
        if body.source_run:
            try:
                run = store.get_run(o, body.source_run)
                same = to_template(run['doc'])[0] == tpl
                src = body.source_run if same and run['status'] not in ('waiting', 'queued', 'running') else None
            except Exception:
                src = None
        try:
            cid = save(store, o, tpl, body.title, body.sub, body.kind, 'made', now(), source_run=src)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {'id': cid, 'card': 'my:' + cid, 'with_receipt': bool(src)}

    @app.post('/api/mycards/{cid}/hide')
    def my_hide(cid: str, request: Request):
        try:
            hide(store, owner(request), cid)
        except LookupError:
            raise HTTPException(404, 'card_not_found')
        return {'ok': True}

    @app.get('/api/mycards/{cid}/export')
    def my_export(cid: str, request: Request):
        from .easy import receipt as make_receipt
        o = owner(request)
        try:
            cd = get_card(store, o, cid)
        except LookupError:
            raise HTTPException(404, 'card_not_found')
        rc = cd.get('receipt')
        if not rc and cd.get('source_run'):
            try:
                run = store.get_run(o, cd['source_run'])
                if run['status'] not in ('waiting', 'queued', 'running'):
                    rc = make_receipt(run, lambda pid: store.get_packet(pid, o))
            except Exception:
                rc = None
        with store.connect() as c:
            store.audit(c, o, 'mycard.export', cid, {'receipt': bool(rc)})
        return bundle(cd, rc)

    @app.post('/api/mycards/import', status_code=201)
    def my_import(body: ImportIn, request: Request):
        o = owner(request)
        b = body.bundle
        try:
            tpl = check_bundle(b)
        except ValueError as e:
            raise HTTPException(422, str(e))
        try_run(tpl)
        try:
            cid = save(store, o, tpl, b.get('title'), b.get('sub', ''), b.get('kind', '사실'), 'imported', now(), receipt=b.get('receipt'))
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {'id': cid, 'card': 'my:' + cid, 'title': b.get('title'), 'with_receipt': bool(b.get('receipt'))}
