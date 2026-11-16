"""v0.16 C: 스스로 고치는 근거 사슬 — 막힌 곳(보류 이유 코드)별로 대체안을 제안하고, 사람이 승인하면 바꾼 사슬로 다시 계산한다.

원칙
- 자동으로 바꾸지 않는다. 제안 → 사람 승인 → 새 실행. 원래 실행은 그대로 남는다.
- 근거 수준이 낮아지는 대체(원문 셀 → 공시 API 등)는 downgrade로 분명히 표시한다.
- 대체안이 없으면 「모름」을 그대로 둔다 (숫자를 채우려고 근거를 낮추지 않는다).
- 바꾼 이력은 문서 meta.repairs에 남고 근거 확인서 확인 번호에도 들어간다.
"""
import copy

from .specs import SPECS, COMPANIES


def _downstream(doc, start):
    out, todo = set(), [start]
    while todo:
        x = todo.pop()
        for e in doc['edges']:
            if e['from_node'] == x and e['to_node'] not in out:
                out.add(e['to_node']); todo.append(e['to_node'])
    return out


def _name(t):
    return SPECS[t]['display_name']


def _required_from(doc, nid, src):
    """nid가 src에서 받는 입력이 필수 입력인가."""
    t = next(n['type'] for n in doc['nodes'] if n['id'] == nid)
    req = {p['name'] for p in SPECS[t]['inputs'] if p['required']}
    return any(e['to_node'] == nid and e['from_node'] == src and e['to_port'] in req for e in doc['edges'])


def suggest(run, get_packet):
    doc = run['doc']
    nodes = {n['id']: n for n in doc['nodes']}
    st = {n['node_id']: n for n in run['nodes']}
    props = []

    def add(pid, node, problem, fix, patch, downgrade=None):
        if any(p['id'] == pid for p in props):
            return
        props.append({'id': pid, 'node': node, 'node_name': _name(nodes[node]['type']), 'problem': problem, 'fix': fix,
                      'downgrade': downgrade, 'patch': patch})

    for nid, r in st.items():
        t, code, status = r['node_type'], r.get('error_code'), r['status']
        cfg = nodes.get(nid, {}).get('config', {})
        # 1) 원문 자료판이 기준시점보다 새것 → 공시 API 재무(T11)로 대체 (근거 수준 낮아짐)
        if t == 'T01' and code == 'cutoff_before_corpus':
            users = [e['to_node'] for e in doc['edges'] if e['from_node'] == nid and nodes[e['to_node']]['type'] in ('N01', 'N05')]
            cos = set()
            for u in users:
                cos |= set(nodes[u]['config'].get('companies') or (list(COMPANIES) if nodes[u]['type'] == 'N01' else [])) or set()
            meta_co = (doc.get('meta') or {}).get('company')
            if not cos and meta_co:
                cos = {meta_co}
            if users and cos:
                add(f'swap-t01-{nid}', nid, '공식 원문 자료판은 2026-11-02 이후 기준 날짜에만 쓸 수 있어요.',
                    f"그 날짜에 이미 접수돼 있던 사업보고서의 공시 API 재무로 바꿔 계산해요 ({', '.join(COMPANIES.get(c, c) for c in sorted(cos))}).",
                    {'op': 'swap_t01_t11', 't01': nid, 'users': users, 'companies': sorted(cos)},
                    '원문 표 칸과 직접 대조한 값 → 공시 API 값 (두 기준 회사는 68/68 일치 확인된 경로)')
        # 2) 가격 이력이 짧음 → 더 긴 기간 불러오기
        if t in ('N09', 'N10') and code == 'too_short':
            src = next((e['from_node'] for e in doc['edges'] if e['to_node'] == nid and nodes[e['from_node']]['type'] == 'T06'), None)
            if src and int(nodes[src]['config'].get('lookback') or 260) < 520:
                add(f'lookback-{src}', src, '계산에 필요한 거래일 수가 모자라요.', '주가를 520거래일(약 2년)까지 불러와 다시 계산해요.',
                    {'op': 'set_config', 'node': src, 'key': 'lookback', 'value': 520})
        if t == 'N15' and code == 'too_short':          # v0.17 관계 기록: 월간 24개월 이상 필요
            src = next((e['from_node'] for e in doc['edges'] if e['to_node'] == nid and nodes[e['from_node']]['type'] == 'T06'), None)
            if src and int(nodes[src]['config'].get('lookback') or 260) < 1300:
                add(f'lookback-{src}', src, '관계를 재려면 24개월 이상의 주가가 필요해요.', '주가를 1,300거래일(약 5년)까지 불러와 다시 재요.',
                    {'op': 'set_config', 'node': src, 'key': 'lookback', 'value': 1300})
        # 3) 공시·뉴스 기간 안에 없음 → 기간 늘리기
        if t == 'T08' and code == 'no_rows' and int(cfg.get('lookback_days') or 180) < 365:
            add(f'lookback-{nid}', nid, '살펴본 기간 안에 공시·뉴스가 없어요.', '살펴볼 기간을 365일로 늘려요.',
                {'op': 'set_config', 'node': nid, 'key': 'lookback_days', 'value': 365})
        # 4) 실적: 기준 날짜에 아직 없는 연도 → 직전 연도로
        if t == 'N01' and status in ('partial', 'held') and r['output_packet']:
            p = get_packet(r['output_packet'])['payload']
            years = [int(y) for y in (cfg.get('years') or [2024, 2025])]
            miss_years = sorted({int(m['period']) for m in p.get('missing', []) if '접수된' in m.get('reason', '')})
            if miss_years and max(miss_years) == max(years):
                new = sorted({y for y in years if y not in miss_years} | {min(years) - 1})
                if new != years:
                    add(f'years-{nid}', nid, f"{', '.join(map(str, miss_years))}년 사업보고서가 그 기준 날짜에는 아직 없었어요.",
                        f"이미 나와 있던 {', '.join(map(str, new))}년으로 바꿔 계산해요.",
                        {'op': 'set_config', 'node': nid, 'key': 'years', 'value': new}, '더 오래된 연도의 실적')
        # 5) 보조 원문(T02)이 비어 있는데 받는 쪽에 꼭 필요하지 않음 → 그 연결만 빼기
        if t == 'T02' and status == 'held':
            opt = [e for e in doc['edges'] if e['from_node'] == nid and not _required_from(doc, e['to_node'], nid)]
            if opt and len(opt) == sum(1 for e in doc['edges'] if e['from_node'] == nid):
                add(f'drop-{nid}', nid, '사업보고서 원문에서 대조할 문단을 쓸 수 없어요.',
                    '원문 대조 없이 공시 기록만으로 계산해요 (원문 대조 항목은 빠져요).',
                    {'op': 'remove_node', 'node': nid}, '원문 문단 대조 생략')
        # 6) 자료가 아예 없는 도구 → 그 자료가 필요한 계산만 빼고 나머지로 답하기 (숫자를 대신 채우지 않음)
        if t in ('T06', 'T07') and code == 'no_rows':
            down = _downstream(doc, nid)
            need = [d for d in down if nodes[d]['type'] != 'T05' and _required_from(doc, d, nid)]
            keep = [n for n in doc['nodes'] if n['id'] not in need and n['id'] != nid and n['type'] not in ('T05',) and n['type'].startswith('N')]
            if need and keep:
                add(f'skip-{nid}', nid, f"{_name(t)}가 이 회사·기간에는 없어요.",
                    f"이 자료가 꼭 필요한 계산({', '.join(_name(nodes[d]['type']) for d in need)})은 빼고 나머지로 답해요. 빠진 것은 「아직 모르는 것」에 남아요.",
                    {'op': 'remove_nodes', 'nodes': [nid] + need})
        # 7) 환율·금리 영향에 거시 자료가 연결 안 됨 → 연결
        if t == 'N06' and status == 'partial' and not any(e['to_node'] == nid and e['to_port'] == 'macro' for e in doc['edges']):
            add(f'macro-{nid}', nid, '올해 실제 환율·금리 변화가 연결돼 있지 않아요.', '거시 지표 자료를 이어 「이 가정이라면」 영향을 계산해요.',
                {'op': 'add_macro', 'node': nid})
    return props


def apply(doc, props, ids):
    """선택한 제안을 적용한 새 문서. 원래 문서는 바꾸지 않는다."""
    d = copy.deepcopy(doc)
    chosen = [p for p in props if p['id'] in ids]
    if not chosen:
        raise ValueError('적용할 제안을 고르세요.')
    for p in chosen:
        pt = p['patch']
        nodes = {n['id']: n for n in d['nodes']}
        op = pt['op']
        if op == 'set_config':
            nodes[pt['node']]['config'][pt['key']] = pt['value']
        elif op == 'remove_node':
            d['nodes'] = [n for n in d['nodes'] if n['id'] != pt['node']]
            d['edges'] = [e for e in d['edges'] if pt['node'] not in (e['from_node'], e['to_node'])]
        elif op == 'remove_nodes':
            gone = set(pt['nodes'])
            d['nodes'] = [n for n in d['nodes'] if n['id'] not in gone]
            d['edges'] = [e for e in d['edges'] if e['from_node'] not in gone and e['to_node'] not in gone]
        elif op == 'swap_t01_t11':
            t01 = nodes[pt['t01']]
            d['edges'] = [e for e in d['edges'] if e['from_node'] != pt['t01']]
            d['nodes'] = [n for n in d['nodes'] if n['id'] != pt['t01']]
            for i, co in enumerate(pt['companies']):
                tid = f't11r{i}' if f't11r{i}' not in nodes else f't11r{i}x'
                d['nodes'].append({'id': tid, 'type': 'T11', 'config': {'company': co, 'snapshot': ''}, 'x': t01.get('x', 40), 'y': t01.get('y', 40) + 120 * i})
                for u in pt['users']:
                    d['edges'].append({'from_node': tid, 'from_port': 'filings', 'to_node': u, 'to_port': 'filings'})
            for u in pt['users']:
                un = next(n for n in d['nodes'] if n['id'] == u)
                if un['type'] == 'N01':
                    un['config']['companies'] = []
        elif op == 'add_macro':
            if not any(n['type'] == 'T10' for n in d['nodes']):
                d['nodes'].append({'id': 't10r', 'type': 'T10', 'config': {}, 'x': 40, 'y': 600})
            t10 = next(n['id'] for n in d['nodes'] if n['type'] == 'T10')
            d['edges'].append({'from_node': t10, 'from_port': 'macro', 'to_node': pt['node'], 'to_port': 'macro'})
        else:
            raise ValueError(op)
    m = d.setdefault('meta', {})
    m['repairs'] = list(m.get('repairs') or []) + [{k: p[k] for k in ('id', 'node_name', 'problem', 'fix', 'downgrade')} for p in chosen]
    return d
