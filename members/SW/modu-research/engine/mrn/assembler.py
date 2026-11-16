"""목표부터 조립 에이전트 (1차판, 규칙 기반 · 모델 0회).

질문 → 목표 노드·설정값 → 노드 등록부의 입출력 자료형을 따라 거꾸로 앞 노드를 깐다.
- 사람이 정해야 하는 곳(T03 가정, T04 보고서 선택)은 배치만 하고 「사람 차례」로 표시한다.
- 아직 준비 중인 노드가 필요한 질문은 지어내지 않고 「아직 답할 수 없는 부분」으로 밝힌다.
- 매수·매도·주가 방향 판단은 하지 않는다.
조립 결과는 감사 기록(agent.assemble)으로 남아 「질문 유형 → 근거 사슬」 지도의 재료가 된다.
"""
import re
from collections import Counter, defaultdict
from .specs import SPECS, REGISTRY, COMPANIES
from .planner import TRADE, KNOWN_COMPANIES, OTHER_CO

# 목표: 노드(또는 예정 노드)마다 「이런 말이 나오면」 단어표. 숫자 = 무게(그 노드만의 말일수록 큼).
GOALS = [
    {'id': 'N01', 'label': '공시로 확인된 실적·재무 숫자',
     'kw': {'매출': 2, '영업이익': 2, '실적': 2, '현금흐름': 2, '재무제표': 2, '재무': 1, '부채': 2, '자산': 2, '자본': 1, '재고': 2,
            '순이익': 1, '이익': 1, '공시된 숫자': 2, '숫자': 1, '얼마': 1, '설비투자': 2, '유형자산': 2, '영업활동': 2, '번 현금': 2, '벌어': 1}},
    {'id': 'N02', 'label': '가정에 따른 기업가치 계산(DCF 등)',
     'kw': {'기업가치': 3, '가치평가': 3, '적정': 2, 'dcf': 3, '주당가치': 3, '밸류': 2, '내재가치': 3, 'ddm': 3, 'rim': 3, 'nav': 3,
            '할인율': 2, '정상화': 2, '말기가치': 3, '가치': 1}},
    {'id': 'N05', 'label': '금리·환율 관측과 회사가 공시한 노출',
     'kw': {'금리': 2, '환율': 2, '달러': 2, '원화': 2, '거시': 2, '매크로': 2, '경기': 1, '통화정책': 2, '기준금리': 2, '노출': 2}},
    {'id': 'N06', 'label': '공시 민감도 × 실제 환율·금리 변화 (이 가정이라면)',
     'kw': {'민감도': 3, '충격': 2, '영향 크기': 2, '얼마나 영향': 2, '변하면': 2, '오르면': 1, '내리면': 1, '시나리오': 1, '환율 영향': 3, '금리 영향': 3, '변화 영향': 3, '이 가정이라면': 2}},
    {'id': 'N09', 'label': '주가 흐름·이동평균·거래량 기본',
     'kw': {'주가': 2, '이동평균': 3, '이평': 3, '수익률': 2, '추세': 2, '차트': 2, '거래량': 2, '52주': 3, '고점': 1, '저점': 1,
            '기술적': 2, '주가 흐름': 3, '거래대금': 2}},
    {'id': 'N10', 'label': '변동성·최대 낙폭·거래량 급증·국면',
     'kw': {'변동성': 3, '낙폭': 3, '하락폭': 3, 'mdd': 3, '급증': 2, '급등락': 2, '얼마나 빠졌': 3, '출렁': 2, '국면': 3, '상승장': 3, '하락장': 3, '횡보': 3, '상승 추세': 2, '하락 추세': 2}},
    {'id': 'N07', 'label': '수급 현황(외국인·기관·개인 순매수, 대차잔고)',
     'kw': {'외국인': 3, '기관': 2, '개인': 1, '수급': 3, '순매수': 3, '순매도': 3, '매매동향': 3, '공매도': 2, '대차': 3, '보유율': 3, '누가 샀': 3, '누가 팔': 3}},
    {'id': 'N08', 'label': '수급 전환·가격과 엇갈림',
     'kw': {'수급 전환': 3, '엇갈': 3, '불일치': 3, '반대로': 2, '순매수인데': 3, '순매도인데': 3, '팔았는데': 3, '샀는데': 3, '방향 전환': 3}},
    {'id': 'N03', 'label': '반도체 비교기업과 재무 비교(성장률·이익률·부채비율·시총 순위)',
     'kw': {'비교기업': 3, 'peer': 3, '경쟁사': 3, '업계': 2, '동종': 3, '마이크론': 3, '엔비디아': 3, 'tsmc': 3, '경쟁': 2, '순위': 2, '대비': 1, '산업': 1, '비교': 1}},
    # ---- 아직 준비 중(조립하지 않고 「아직 답할 수 없음」으로 기록) ----
    {'id': 'N04', 'label': '경쟁력·점유율 (사업보고서 문장 발췌)',
     'kw': {'점유율': 3, '경쟁력': 3, '기술력': 3, '업황': 2, 'hbm': 2, '경쟁 우위': 3, '시장 규모': 3}},
    {'id': 'N11', 'label': '공시·뉴스 사건과 관심도(감성 점수는 규칙 값)',
     'kw': {'뉴스': 3, '이슈': 2, '심리': 2, '여론': 3, '감성': 3, '커뮤니티': 3, '루머': 3, '언급': 2, '최근 공시': 3, '공시 목록': 3, '사건': 2, '관심도': 3, '화제': 3}},
    {'id': 'N12', 'label': '공시 뒤 주가·거래량 반응',
     'kw': {'공시 뒤': 3, '공시 후': 3, '발표 후': 3, '발표 뒤': 3, '주가 반응': 3, '시장 반응': 3, '반응': 2, '이벤트': 2, '사건 후': 3, '공시 나오면': 3}},
    {'id': 'N13', 'label': '대주주·경영진 지분 공시',
     'kw': {'대주주': 3, '최대주주': 3, '지분': 2, '경영진': 2, '임원 지분': 3, '오너': 3, '5% 보고': 3, '대량보유': 3, '특수관계인': 3}},
    {'id': 'N14', 'label': '수출 통계로 실적 조기 확인 (모델 추정)',
     'kw': {'수출': 3, '관세청': 3, '조기': 2, '실적 발표 전': 3, '나우캐스트': 3, 'nowcast': 3, '발표 전에': 2}},
    {'id': 'N15', 'label': '주가와 함께 움직인 지표 (관계 기록, 인과 아님)',
     'kw': {'상관': 3, '상관관계': 3, '함께 움직': 3, '같이 움직': 3, '연동': 3, '관계가 있': 2, '관계 있': 2, '영향을 받': 2, '민감하게': 2, '따라 움직': 3, '선행': 3, '동행': 3}},
    {'id': 'N16', 'label': '증권사 실적 전망 추이·집계 (컨센서스 아님)',
     'kw': {'컨센서스': 3, '전망 추이': 3, '추정치': 3, '전망치': 3, '눈높이': 3, '예상치': 3, '증권사들': 2, '전망 변화': 3}},
    {'id': 'BOARD', 'label': '이사회·임원 구성과 보수 (자료 없음)', 'gap': True,
     'kw': {'이사회': 3, '사외이사': 3, '임원 구성': 3, '보수': 2, '경영진 구성': 3}},
    {'id': 'DOCS', 'label': '사업보고서 문장 검색 (「문서·재무」 화면)', 'gap': True, 'tool': True,
     'kw': {'사업보고서에서': 3, '리스크 요인': 3, '위험 요인': 3, '사업의 내용': 3, '주석': 2, '어디에 나와': 3, '원문에서': 2}},
]
GOAL = {g['id']: g for g in GOALS}
IMPL_RANK = {'real': 0, 'partial': 1, 'not_connected': 2}
PEER_NAMES = {'마이크론', '엔비디아', 'TSMC'}   # 비교 대상으로는 쓸 수 있음(N03)
BROKER_WORDS = ('증권사', '전망', '컨센서스', '리포트', '애널리스트')
CHOICES = ['N01', 'N09', 'N05', 'N02']
YEARS = (2024, 2025)
METRIC_WORDS = {'매출': 'revenue', '영업이익': 'operatingProfit', '현금흐름': 'cfo', '유동자산': 'currentAssets', '유동부채': 'currentLiabilities',
                '자산': 'assets', '부채': 'liabilities', '자본': 'equity', '재고': 'inventory', '유형자산': 'ppeAcquisition',
                '설비투자': 'ppeAcquisition', '무형자산': 'intangibleAcquisition'}


def _score(q, goal):
    hits, s, top = [], 0, 0
    found = [k for k in goal['kw'] if k in q]
    for k in found:
        if any(k != o and k in o for o in found):      # 「가치」가 「기업가치」 안에 있으면 한 번만 센다
            continue
        w = goal['kw'][k]; hits.append(k); s += w; top = max(top, w)
    return (s if top >= 2 else min(s, 1)), hits     # 흔한 단어(무게 1)만으로는 목표를 확정하지 않는다


def parse(question, pick=None):
    q = (question or '').strip()[:500]
    ql = q.lower()
    companies = []
    notes = []
    names = _names()
    rest = q
    for name in sorted(names, key=len, reverse=True):         # 긴 이름부터: 「한화에어로스페이스」가 「한화」보다 먼저
        if len(name) >= 2 and name in rest:
            if names[name] not in companies:
                companies.append(names[name])
                fam = sorted(n for n in names if n != name and n.startswith(name))
                if len(name) <= 3 and fam:
                    notes.append(f"「{name}」이라는 이름의 회사로 봤어요. {', '.join(fam[:4])} 등을 말씀하신 거라면 정확한 이름을 적어 주세요.")
            rest = rest.replace(name, ' ' * len(name))
    for code in re.findall(r'(?<!\d)(\d{6})(?!\d)', q):
        if code in _codes() and code not in companies:
            companies.append(code)
    pos = {c: min([q.find(n) for n, t in names.items() if t == c and n in q] + [q.find(c) if c in q else 999]) for c in companies}
    companies.sort(key=lambda c: pos[c] if pos[c] >= 0 else 999)
    for name, code in KNOWN_COMPANIES.items():               # 줄임말(삼성·하이닉스)
        if name.lower() in rest.lower() and code not in companies:
            companies.append(code)
            if name == '삼성':
                fam = sorted(n for n in names if n.startswith('삼성') and n != '삼성전자')[:4]
                if fam:
                    notes.append(f"「삼성」은 삼성전자로 봤어요. {', '.join(fam)} 같은 다른 회사라면 이름을 정확히 적어 주세요.")
    years = sorted({int(y) for y in re.findall(r'20\d\d', q) if int(y) in YEARS})
    metrics = []
    q_plain = q.replace('유동자산', '').replace('유형자산', '').replace('무형자산', '')
    for w, m in METRIC_WORDS.items():
        if (w in (q_plain if w == '자산' else q)) and m not in metrics:
            metrics.append(m)
    scored = []
    ql_goal = rest.lower()          # v0.24.3: 회사 이름을 지운 글로 목표를 찾는다(「현대차」 안의 「대차」가 수급으로 잡히던 문제)
    for g in GOALS:
        s, hits = _score(ql_goal, g)
        if s:
            scored.append((s, g['id'], hits))
    if pick:
        scored = [(9, p, ['직접 고름']) for p in pick if p in GOAL]
    strong = [x for x in scored if x[0] >= 2]          # 1점짜리 약한 단서만으로는 확정하지 않는다
    q_trade = re.sub(r'순매수|순매도|매수세|매도세|매매동향', '', q)    # 수급 용어는 매매 판단 요청이 아님
    if TRADE.search(q_trade):
        notes.append('사거나 팔지, 오를지 내릴지는 판단하지 않아요. 대신 확인된 사실과 「이 가정이라면」의 계산을 보여 드려요.')
    other = sorted(w for w in set(OTHER_CO.findall(rest)) - PEER_NAMES if not any(n.startswith(w) and n in q for n in names))
    amb = [w for w in other if sum(1 for n in names if n.startswith(w)) > 1]
    for w in amb:
        cands = sorted(n for n in names if n.startswith(w))
        notes.append(f"「{w}」로 시작하는 회사가 {len(cands)}곳 있어요({', '.join(cands[:5])}{' 등' if len(cands) > 5 else ''}). 정확한 이름을 적어 주세요.")
    other = [w for w in other if w not in amb and not any(n.startswith(w) for n in names)]
    peers_named = sorted(set(OTHER_CO.findall(q)) & PEER_NAMES)
    if peers_named and not any(w in q for w in ('비교', '대비', '경쟁', '동종', '순위')):
        notes.append(f"{', '.join(peers_named)}는 비교 대상(재무 비율 비교, N03)으로만 쓸 수 있어요. 주가·수급·가치평가는 삼성전자·SK하이닉스만 가능해요.")
    if other:
        notes.append(f"{', '.join(other)}는 아직 자료가 없어 조사할 수 없어요. 「근거 지도」에서 자료가 있는 회사를 볼 수 있어요.")
    return {'question': q, 'companies': companies, 'years': years, 'metrics': metrics,
            'goals': sorted(strong, key=lambda x: -x[0]), 'weak': [x for x in scored if x[0] < 2], 'notes': notes,
            'trade': bool(TRADE.search(q_trade)), 'other_companies': other}


def _names():
    from .market import name_index
    return name_index() or {}


def _codes():
    return set(_names().values()) | set(COMPANIES)


def co_name(t):
    if t in COMPANIES:
        return COMPANIES[t]
    return next((n for n, c in _names().items() if c == t), t)


MARKET_WIDE = ('N09', 'N10', 'N07', 'N08', 'N11', 'N12', 'N13', 'N15', 'N16')   # 키트 1: 사본의 모든 국내 기업에 쓸 수 있는 노드
FILINGS_WIDE = ('N01', 'N05', 'N06')         # 키트 2: T11(공시 API 재무·민감도)로 다른 회사도 가능
ANY_CO = MARKET_WIDE + FILINGS_WIDE


def _producers(type_):
    return sorted([s for s in REGISTRY if any(o['type'] == type_ for o in s['outputs'])],
                  key=lambda s: (IMPL_RANK[s['implementation']], 0 if s['tier'] == 'tool' else 1))


class _Builder:
    def __init__(self):
        self.nodes, self.edges, self.by_key, self.human = [], [], {}, []

    def node(self, type_, cfg=None, key=None):
        key = key or (type_,)
        if key in self.by_key:
            return self.by_key[key]
        base = type_.lower(); nid = base; i = 1
        while any(n['id'] == nid for n in self.nodes):
            i += 1; nid = f'{base}-{i}'
        conf = {k: v.get('default') for k, v in SPECS[type_]['config_schema'].items()}
        conf.update(cfg or {})
        self.nodes.append({'id': nid, 'type': type_, 'config': conf})
        self.by_key[key] = nid
        return nid

    def edge(self, a, ap, b, bp):
        e = {'from_node': a, 'from_port': ap, 'to_node': b, 'to_port': bp}
        if e not in self.edges:
            self.edges.append(e)

    def feed(self, nid, company=None, want_broker=False, depth=0):
        """nid의 필수 입력(그리고 요청된 경우 증권사 전망 입력)을 거꾸로 채운다."""
        sp = SPECS[next(n['type'] for n in self.nodes if n['id'] == nid)]
        for inp in sp['inputs']:
            if not inp['required'] and not inp.get('auto') and not (inp['type'] == 'BrokerForecastPackage' and want_broker) and inp['type'] != 'MacroSeries':
                continue
            if any(e['to_node'] == nid and e['to_port'] == inp['name'] for e in self.edges):
                continue
            prods = _producers(inp['type'])
            if not prods or depth > 5:
                continue
            p = prods[0]
            cfg, key = {}, None
            if p['id'] in ('T06', 'T07', 'T08', 'T09', 'T11', 'T12', 'T13'):
                cfg, key = {'company': company or '005930'}, (p['id'], company or '005930')
            elif p['id'] == 'T02':
                pre = {'N13': 'holders'}.get(sp['id'], 'competition')
                cfg, key = {'company': company or '005930', 'preset': pre, 'k': 20 if pre == 'competition' else 10}, ('T02', company or '005930', pre)
            elif p['id'] in ('T03', 'T04'):
                key = (p['id'], nid)
            pid = self.node(p['id'], cfg, key)
            if p['id'] == 'T03' and not any(h['node'] == pid for h in self.human):
                self.human.append({'node': pid, 'type': 'T03', 'for': nid,
                                   'what': '가치평가 가정(할인율·성장률·주식 수 등)은 사람이 넣어야 해요. 설정 탭의 「학습용 예시」로 먼저 채워 볼 수 있어요.'})
            if p['id'] == 'T04' and not any(h['node'] == pid for h in self.human):
                self.human.append({'node': pid, 'type': 'T04', 'for': nid,
                                   'what': '어느 증권사 보고서를 쓸지 사람이 골라야 해요. 「증권사 전망」 화면에서 사람이 승인한 전망만 쓸 수 있어요.'})
            out = next(o for o in p['outputs'] if o['type'] == inp['type'])
            self.edge(pid, out['name'], nid, inp['name'])
            self.feed(pid, company, False, depth + 1)

    def layout(self):
        preds = defaultdict(list)
        for e in self.edges:
            preds[e['to_node']].append(e['from_node'])
        depth = {}

        def d(n, seen=()):
            if n in depth:
                return depth[n]
            if n in seen:
                return 0
            depth[n] = 1 + max((d(p, seen + (n,)) for p in preds[n]), default=-1)
            return depth[n]
        rows = Counter()
        for n in self.nodes:
            k = d(n['id']); n['x'] = 40 + k * 300; n['y'] = 40 + rows[k] * 150; rows[k] += 1
        for n in self.nodes:                        # 취합(T05)은 앞 노드들의 가운데 높이에서 조금 아래로 — 선이 다른 노드를 가로지르지 않게
            if n['type'] == 'T05' and preds[n['id']]:
                ys = [m['y'] for m in self.nodes if m['id'] in preds[n['id']]]
                n['y'] = int(sum(ys) / len(ys)) + 75


def _choices():
    return [{'id': g, 'label': GOAL[g]['label']} for g in CHOICES]


def assemble(question, pick=None, cutoff=''):
    P = parse(question, pick)
    out = {'question': P['question'], 'notes': list(P['notes']), 'companies': P['companies'], 'years': P['years'],
           'targets': [], 'gaps': [], 'human': [], 'chains': [], 'doc': None, 'status': 'ok', 'choices': [], 'method': 'rule'}
    if not P['goals']:
        out['status'] = 'ask'
        weak = [h for x in P['weak'] for h in x[2]]
        out['ask'] = '무엇을 보고 싶은지 확실히 찾지 못했어요. 가장 가까운 것을 골라 주세요.' + (f" (걸린 단어: {', '.join(weak)})" if weak else '')
        out['choices'] = _choices()
        return out
    targets = [g for _, g, _ in P['goals'] if not GOAL[g].get('gap')]
    hits = {g: h for _, g, h in P['goals']}
    for _, g, h in P['goals']:
        if GOAL[g].get('gap'):
            gd = GOAL[g]
            why = ('「문서·재무」 화면의 사업보고서 검색으로 찾아볼 수 있어요.' if gd.get('tool') else
                   '이 노드는 아직 준비 중이라 이번 계획에서 뺐어요.' if g in SPECS else '아직 만들지 않은 노드예요 (만들 계획에 있어요).')
            out['gaps'].append({'id': g, 'label': gd['label'], 'hits': h, 'why': why})
    if 'N06' in targets and 'N05' in targets:      # N06이 N05를 이미 포함
        targets.remove('N05')
    if 'N08' in targets and 'N07' not in targets:   # 엇갈림을 보려면 현황도 함께
        targets.insert(targets.index('N08'), 'N07')
    if not targets:
        out['status'] = 'gap_only'
        out['notes'].append('물어보신 내용은 아직 준비 중인 부분이라 지금 계산할 노드가 없어요. 지금 볼 수 있는 것 중에서 고를 수 있어요.')
        out['choices'] = _choices()
        return out
    others = [c for c in P['companies'] if c not in COMPANIES]
    base_only = [t for t in targets if t not in ANY_CO]
    if others and base_only:
        lab = ', '.join(dict.fromkeys(GOAL[t]['label'] for t in base_only))
        out['notes'].append(f"{', '.join(co_name(c) for c in others)}: 「{lab}」은 아직 삼성전자·SK하이닉스만 돼요. 주가·추세·수급과 사업보고서 실적·공시 민감도는 볼 수 있어요.")
        out['gaps'].append({'id': 'BASE_ONLY', 'label': lab + ' (다른 기업)', 'hits': [], 'why': '가치평가(증권사 전망·원문 셀 대조)와 반도체 비교군은 아직 두 기준 기업만 있어요.'})
    if others and not [t for t in targets if t in ANY_CO]:
        out['status'] = 'gap_only'
        out['notes'].append('이 회사로 지금 볼 수 있는 것: 주가·거래량, 추세 구간, 투자자별 수급, 가격과 수급의 엇갈림, 사업보고서 실적·현금흐름, 공시된 환율·금리 민감도.')
        out['choices'] = _choices()
        return out
    if others and not [c for c in P['companies'] if c in COMPANIES]:
        targets = [t for t in targets if t in ANY_CO]      # 묻지 않은 삼성전자·SK하이닉스 계산은 넣지 않는다
    B = _Builder()
    cos = P['companies'] or list(COMPANIES)
    want_broker = any(w in P['question'] for w in BROKER_WORDS)
    for t in targets:
        if t in ('N09', 'N10', 'N07', 'N08', 'N11', 'N12', 'N13', 'N03', 'N04', 'N14', 'N15', 'N16'):
            for co in cos:
                if t not in MARKET_WIDE and co not in COMPANIES:
                    continue
                nid = B.node(t, {}, (t, co)); B.feed(nid, co)
                if t == 'N13' and co in COMPANIES:          # 원문(주주 문단)과 대조
                    did = B.node('T02', {'company': co, 'preset': 'holders'}, ('T02', co, 'holders')); B.edge(did, 'docs', nid, 'docs')
                if t == 'N04':                             # 비교군도 함께
                    pid = B.node('T09', {'company': co}, ('T09', co)); B.edge(pid, 'peers', nid, 'peers')
                out['targets'].append({'node': nid, 'type': t, 'company': co, 'hits': hits.get(t, []), 'label': GOAL[t]['label']})
        elif t == 'N02':
            for co in ([c for c in P['companies'] if c in COMPANIES] or ['005930']):
                cfg = {'company': co, 'apply_forecast': 'yes' if want_broker and co == '005930' else 'no'}
                if P['years']:
                    cfg['base_year'] = P['years'][-1]
                nid = B.node('N02', cfg, ('N02', co)); B.feed(nid, co, want_broker and co == '005930')
                out['targets'].append({'node': nid, 'type': 'N02', 'company': co, 'hits': hits.get(t, []), 'label': GOAL[t]['label']})
            if want_broker and '000660' in P['companies']:
                out['notes'].append('증권사 보고서는 삼성전자 것만 있어요. SK하이닉스 가치평가에는 증권사 전망을 넣지 않았어요.')
        else:
            cfg = {}
            if t == 'N01':
                if [c for c in P['companies'] if c in COMPANIES]:
                    cfg['companies'] = [c for c in P['companies'] if c in COMPANIES]
                if P['years']:
                    cfg['years'] = P['years']
                if P['metrics']:
                    cfg['metrics'] = list(dict.fromkeys(P['metrics'] + ['revenue', 'operatingProfit']))
            bases = [c for c in P['companies'] if c in COMPANIES]
            if t == 'N01' and others and not bases:
                cfg['companies'] = []
            nid = B.node(t, cfg); B.feed(nid)
            out['targets'].append({'node': nid, 'type': t, 'company': None, 'hits': hits.get(t, []), 'label': GOAL[t]['label']})
            if others:                              # 다른 회사: T11 → N01·N05 filings
                host = nid if t in ('N01', 'N05') else next((e['from_node'] for e in B.edges if e['to_node'] == nid and e['to_port'] == 'exposure'), None)
                for co in others:
                    tid = B.node('T11', {'company': co}, ('T11', co))
                    B.edge(tid, 'filings', host, 'filings')
                if not bases and P['companies']:     # 묻지 않은 두 기준 기업의 원문(T01)은 떼어 낸다
                    t01 = [e for e in B.edges if e['to_node'] == host and e['to_port'] == 'corpus']
                    for e in t01:
                        B.edges.remove(e)
                        if not any(x['from_node'] == e['from_node'] for x in B.edges):
                            B.nodes[:] = [n for n in B.nodes if n['id'] != e['from_node']]
                            B.by_key = {k: v for k, v in B.by_key.items() if v != e['from_node']}
    n02 = [m for m in B.nodes if m['type'] == 'N02']
    for n in B.nodes:                               # N02가 쓰는 회사·연도를 N01 범위에 포함
        if n['type'] == 'N01' and n02:
            n['config']['companies'] = sorted(set(n['config'].get('companies') or []) | {m['config']['company'] for m in n02})
            n['config']['years'] = sorted(set(n['config'].get('years') or []) | {m['config']['base_year'] for m in n02})
    for n in B.nodes:                               # N15(관계 기록)는 월간 24개월 이상 → 주가 1,300거래일
        if n['type'] == 'T06' and any(e['from_node'] == n['id'] and next(m['type'] for m in B.nodes if m['id'] == e['to_node']) == 'N15' for e in B.edges):
            n['config']['lookback'] = 1300
    if len(out['targets']) > 1:
        rid = B.node('T05')
        for t in out['targets']:
            B.edge(t['node'], SPECS[t['type']]['outputs'][0]['name'], rid, 'results')
    B.layout()
    out['doc'] = {'name': '질문: ' + P['question'][:60], 'cutoff': cutoff, 'nodes': B.nodes, 'edges': B.edges}
    out['human'] = B.human
    preds = defaultdict(list)
    for e in B.edges:
        preds[e['to_node']].append(e['from_node'])
    typ = {n['id']: n['type'] for n in B.nodes}

    def chain(nid):
        p = preds[nid]
        if not p:
            return typ[nid]
        if len(p) == 1:
            return chain(p[0]) + ' → ' + typ[nid]
        return '(' + ' + '.join(chain(x) for x in p) + ') → ' + typ[nid]
    for t in out['targets']:
        sp = SPECS[t['type']]
        lim = '' if sp['implementation'] == 'real' else ' 일부만 동작해요: ' + sp['description']
        co = f" · {co_name(t['company'])}" if t['company'] else ''
        out['chains'].append({'target': t['node'], 'type': t['type'], 'chain': chain(t['node']),
                              'text': f"{t['label']}{co} — 질문의 「{'·'.join(t['hits'][:3])}」에 답해요.{lim}"})
    out['signature'] = ' | '.join(sorted({c['chain'] for c in out['chains']}))
    return out


# ---------------------------------------------------------------- C: 질문 유형 → 근거 사슬 지도
def map_from_audit(rows):
    """rows: 감사 기록(agent.assemble)의 detail 목록. 많이 쓰인 목표, 많이 요청된 빈 노드, 자주 쓰인 근거 사슬."""
    goal_n, gap_n, sig_n = Counter(), Counter(), Counter()
    gap_q = defaultdict(list)
    for r in rows:
        for t in set(r.get('targets') or []):
            goal_n[t] += 1
        for g in set(r.get('gaps') or []):
            gap_n[g] += 1
            if len(gap_q[g]) < 3 and r.get('question'):
                gap_q[g].append(r['question'][:80])
        if r.get('signature'):
            sig_n[r['signature']] += 1
    return {'total': len(rows),
            'goals': [{'id': g, 'label': GOAL.get(g, {}).get('label', g), 'count': c} for g, c in goal_n.most_common()],
            'gaps': [{'id': g, 'label': GOAL.get(g, {}).get('label', g), 'count': c, 'examples': gap_q[g]} for g, c in gap_n.most_common()],
            'chains': [{'chain': s, 'count': c} for s, c in sig_n.most_common(10)]}
