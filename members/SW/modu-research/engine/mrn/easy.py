"""쉬운 화면(v0.15): 질문 카드 → 근거 사슬(고정) → 답 카드 · 근거 확인서.

원칙: 답 카드의 첫 문장은 결론이 아니라 「확인된 사실 · 계산한 값 · 추정 · 아직 모르는 것」의 정리다.
매수·매도·목표주가·예측 단정은 만들지 않는다. 숫자는 모두 노드 결과 패킷에서 그대로 가져온다.
"""
import hashlib
import json

from .specs import COMPANIES, KINDS, SPECS

# 배지 3종 (기본 화면) ← 값 종류 8종 (근거 서랍에서 그대로 보여 줌)
TIER = {'fact_official': 'fact', 'fact_portal': 'fact', 'derived': 'calc', 'rule_derived': 'calc',
        'forecast_model': 'estimate', 'forecast_external': 'estimate', 'assumption_user': 'estimate',
        'assumption_illustrative': 'estimate'}
TIER_LABEL = {'fact': '자료로 확인', 'calc': '계산한 값', 'estimate': '추정·가정'}

NOT_THIS = '매수·매도 추천이나 주가 예측이 아닙니다. 판단은 직접 하세요.'


def _n(i, t, **cfg):
    return {'id': i, 'type': t, 'config': cfg, 'x': 0, 'y': 0}


def _e(a, ap, b, bp):
    return {'from_node': a, 'from_port': ap, 'to_node': b, 'to_port': bp}


def _lay(nodes, edges):
    """도구는 왼쪽, 분석은 가운데, 취합은 오른쪽 — 전문가 모드에서 바로 읽히게."""
    col = {'tool': 0, 'basic': 1, 'extension': 1, 'addon': 1}
    rows = {}
    for n in nodes:
        c = 2 if n['type'] == 'T05' else col.get(SPECS[n['type']]['tier'], 1)
        r = rows.get(c, 0)
        n['x'], n['y'] = 40 + c * 380, 40 + r * 170
        rows[c] = r + 1
    return nodes, edges


CARDS = [
    {'id': 'events', 'title': '요즘 무슨 일이 있었나?', 'sub': '최근 공시·뉴스와 공시 뒤 주가 반응', 'needs': ['disclosure'], 'outputs': ['n11', 'n12']},
    {'id': 'price', 'title': '주가 흐름과 누가 샀나?', 'sub': '수익률·추세 구간·외국인/기관 매매', 'needs': ['price_fsc', 'flow'], 'outputs': ['n09', 'n10', 'n07', 'n08']},
    {'id': 'earnings', 'title': '실적은 어땠나?', 'sub': '사업보고서 매출·영업이익·현금흐름', 'needs': ['fin_annual'], 'outputs': ['n01']},
    {'id': 'macro', 'title': '환율·금리가 실적에 주는 영향은?', 'sub': '회사가 공시한 민감도 × 올해 실제 변화 (이 가정이라면)', 'needs': ['exposure'], 'outputs': ['n06', 'n05']},
    {'id': 'holders', 'title': '대주주는 누구고 바뀌었나?', 'sub': '최대주주 지분·5% 보고·임원 보고', 'needs': ['holder'], 'outputs': ['n13']},
    {'id': 'relations', 'title': '무엇과 함께 움직였나?', 'sub': '환율·지수·금리·수출과 주가의 관계 기록 (인과 아님)', 'needs': ['price_fsc'], 'outputs': ['n15'], 'view': 'relmap'},
    {'id': 'forecasts', 'title': '증권사들은 실적을 어떻게 보나?', 'sub': '승인된 보고서의 실적 전망 추이·집계 (컨센서스 아님) · 모두의 가정', 'needs': [], 'needs_ledger': True, 'outputs': ['n16'], 'view': 'forecast'},
    {'id': 'edi', 'title': '주가가 실적보다 몇 년 앞서 있나?', 'sub': '실적이 해마다 8%씩 자란다고 할 때, 실적이 받치는 가치가 지금 주가에 닿기까지 걸리는 햇수 · 적정주가 아님', 'needs': ['price_fsc', 'fin_annual'], 'outputs': ['n17', 'n18']},
    {'id': 'nowcast', 'title': '이번 분기 매출을 미리 가늠할 수 있나?', 'sub': '관세청 수출 통계 × 과거 비율 (모델 추정)', 'needs': [], 'base_only': True, 'outputs': ['n14']},
]
CARD = {c['id']: c for c in CARDS}
# v0.38 T1: 「내 관심 종목」에서 접수번호로 여는 카드 — 카드 목록(CARDS)에는 넣지 않는다(접수번호가 있어야 하므로). 답 카드·확인서·공유는 다른 카드와 같다.
FILING_CARD = {'id': 'filing', 'title': '이 공시는 숫자로 무엇인가?', 'sub': '공시 원문의 칸 값과 시가총액·앞선 공시와 나눈 비율 (방향 판단 아님)', 'needs': ['price_fsc'],
               'outputs': ['n20'], 'group': 'past', 'kind': '사실', 'short': '공시 숫자', 'next': ['events', 'holders'], 'doors': []}
CARD['filing'] = FILING_CARD

# ---------------------------------------------------------------- v0.23 쉬운 화면 1.4: 묶음 · 세 개의 문 · 다음 걸음
# 카드 묶음(사용자가 훑어보기 쉽게) — 값 종류와 맞춘다: 지난 일 = 주로 자료로 확인, 시장 = 관계·흐름, 앞으로 = 가정·전망
GROUPS = [
    {'id': 'past', 'title': '지난 일 확인', 'sub': '공시·통계에 기록된 사실부터'},
    {'id': 'market', 'title': '시장의 움직임', 'sub': '주가·매매·함께 움직인 것'},
    {'id': 'ahead', 'title': '앞으로에 대한 가정', 'sub': '전망과 「이 가정이라면」 계산 — 사실과 섞지 않아요'},
]
# 세 개의 문 — 사람(신원)이 아니라 하려는 일로 나눈다
DOORS = [
    {'id': 'ask', 'title': '궁금한 것 묻기', 'sub': '회사를 고르고 질문 카드를 누르면 근거와 함께 정리해 드려요', 'for': '처음 오셨다면 여기부터'},
    {'id': 'test', 'title': '내 생각 시험하기', 'sub': '내 가정을 적고 증권사·다른 사람들·실제와 나란히 비교해요', 'for': '나름의 생각이 있다면'},
    {'id': 'check', 'title': '근거 검증하기', 'sub': '받은 근거 확인서를 다시 계산하거나, 답이 나온 단계를 하나씩 따라가요', 'for': '숫자를 직접 확인하고 싶다면'},
]
CARD_META = {
    'earnings':  {'group': 'past', 'kind': '사실', 'doors': ['ask', 'check'], 'next': ['forecasts', 'edi', 'macro']},
    'holders':   {'group': 'past', 'kind': '사실', 'doors': ['ask', 'check'], 'next': ['events', 'earnings']},
    'events':    {'group': 'past', 'kind': '사실', 'doors': ['ask'], 'next': ['price', 'holders']},
    'price':     {'group': 'market', 'kind': '사실', 'doors': ['ask'], 'next': ['relations', 'events']},
    'relations': {'group': 'market', 'kind': '관계', 'doors': ['ask', 'test'], 'next': ['macro', 'price']},
    'forecasts': {'group': 'ahead', 'kind': '가정', 'doors': ['ask', 'test'], 'next': ['earnings', 'edi', 'nowcast']},
    'edi':       {'group': 'ahead', 'kind': '가정', 'doors': ['test'], 'next': ['forecasts', 'earnings']},
    'macro':     {'group': 'ahead', 'kind': '가정', 'doors': ['ask', 'test'], 'next': ['relations', 'earnings']},
    'nowcast':   {'group': 'ahead', 'kind': '가정', 'doors': ['test'], 'next': ['forecasts', 'earnings']},
}
# 이 답을 전문가 모드에서 열면 더 알 수 있는 것 — 전문가 모드에 실제로 있는 설정·화면만 적는다
EXPERT_HINT = {
    'events':    ['살펴볼 기간을 바꿔 공시·뉴스를 다시 세기', '공시마다 1·5·20거래일 뒤 주가 반응 전체 표'],
    'price':     ['불러올 거래일 수를 바꿔 다시 계산', '가격과 매매 주체가 엇갈린 날 전체 목록과 단계별 결과'],
    'earnings':  ['다른 연도·항목·여러 회사를 골라 다시 계산', '「문서·재무」에서 사업보고서 원문 표와 공시 재무(XBRL) 값 대조'],
    'macro':     ['회사가 공시한 민감도 문장을 사업보고서 원문에서 직접 찾기', '계산에 쓴 실제 환율·금리 변화 값을 단계마다 확인'],
    'holders':   ['찾을 내용·검색어를 바꿔 사업보고서 원문 문단을 다시 찾기', '찾은 문단마다 원문 위치와 지문(해시) 확인'],
    'relations': ['비교할 지표와 불러올 기간을 바꿔 다시 재기', '시차별 상관·과거 맞히기 시험 결과를 단계에서 직접 보기'],
    'forecasts': ['「증권사 전망」에서 보고서별 원래 숫자와 승인 기록 보기', '받은 보고서를 등록·승인해 집계에 넣기'],
    'edi':       ['자기자본비용·장기성장률·기준 성장률(8%) 가정을 바꿔 다시 계산', '정규화 ROE·최근 4분기·장부가 세 방식의 단계별 값'],
    'nowcast':   ['수출 품목을 바꿔 다시 계산', '과거 맞히기 오차를 분기마다 확인'],
}
for _c in CARDS:
    _c.update(CARD_META.get(_c['id'], {'group': 'past', 'kind': '사실', 'doors': ['ask'], 'next': []}))
    _c['expert'] = EXPERT_HINT.get(_c['id'], [])


# v0.36.2 (R7): 화면용 짧은 이름. 원래 title 은 그대로 둔다.
SHORT = {'events': '최근 주요 사건', 'price': '주가 흐름·매매 주체', 'earnings': '실적 요약', 'macro': '환율·금리 영향', 'holders': '대주주·지분 변동',   # v0.39.1 R11 화면 이름표
         'relations': '함께 움직인 지표', 'forecasts': '증권사 실적 전망', 'edi': '주가 선반영 햇수', 'nowcast': '이번 분기 매출 조기 추정',
         'attention': '관심도 추이', 'reaction': '공시별 과거 주가 반응'}


def hold_id(company, node_type, text):
    """v0.36.2 (D2): 보류 고정 번호 H-<종목>-<8자리>. 같은 회사·같은 단계·같은 사유 문장이면 언제 다시 돌려도 같은 번호."""
    return f"H-{company or 'NA'}-" + hashlib.sha256(f'{node_type}|{text}'.encode()).hexdigest()[:8]


def _llm_configured():
    import os
    return bool(os.environ.get('MODU_NODES_LLM_URL') and os.environ.get('MODU_NODES_LLM_MODEL'))


def process(run, get_packet, items, unknown, sources, repairs):
    """작동 원리 띠: 이 답이 실제로 어떻게 만들어졌는지(기술 이름은 눌렀을 때만). 지어내지 않고 실행 기록에서만 만든다."""
    from .numeric import COMPILED
    doc = run['doc']
    meta = doc.get('meta') or {}
    nodes = run['nodes']
    tools = [n for n in nodes if n['node_type'].startswith('T') and n['node_type'] != 'T05']
    calcs = [n for n in nodes if n['node_type'].startswith('N')]
    ok = ('succeeded', 'partial')
    # 1) 질문 이해·조립 (에이전트)
    card = CARD.get(meta.get('card') or '') or meta.get('my_card')      # v0.36 내 질문 카드도 「질문 카드」로
    manual = not card and meta.get('ui') != 'easy'          # v0.24.2: 전문가 모드에서 사람이 직접 짠 구성(조사 계획·예시 사례·직접 연결)
    planned = meta.get('planned_by') or ('card' if card else 'manual' if manual else 'rule')
    if card:
        plan_txt = f"질문 카드 「{card['title']}」에 맞춰 미리 정해 둔 순서로 {len(nodes)}단계를 이었어요."
    elif manual:
        plan_txt = f"전문가 모드에서 직접 고른 구성(단계 {len(nodes)}개)을 연결 순서대로 실행했어요."
    else:
        plan_txt = f"조립 에이전트가 질문 속 낱말을 규칙으로 읽고 {len(nodes)}단계를 골라 이었어요."
    agent_tech = ('질문 카드 = 고정된 근거 사슬(질문을 잘못 알아듣는 일이 없음)' if card else
                  '사람이 고른 구성 — 연결 관계로 실행 순서를 계산(에이전트가 고르지 않음)' if manual else
                  '조립 에이전트(규칙 기반 계획) — 질문 → 필요한 단계 선택 → 연결 → 실행')
    # 2) 자료 찾기 (도구 · RAG)
    rag = [n for n in tools if n['node_type'] == 'T02']
    rag_n = 0
    for n in rag:
        if n['output_packet'] and n['status'] in ok:
            try:
                rag_n += len(get_packet(n['output_packet'])['payload'].get('hits') or [])
            except Exception:
                pass
    t_ok = sum(1 for n in tools if n['status'] in ok)
    hashed = sum(1 for s in sources if s.get('sha256'))
    find_txt = f"자료 도구 {len(tools)}개 중 {t_ok}개가 자료를 가져왔어요" + (f", 사업보고서 원문에서 관련 문단 {rag_n}개를 찾았어요" if rag else '') + '.'
    find_tech = ('원문 검색(RAG의 「찾아오기」 단계, BM25 낱말 검색) — 찾은 문단마다 원문 해시를 붙임' if rag else
                 '정해진 자료원(공시·통계·시세 사본)에서 그대로 불러오기 — 검색 결과를 지어내지 않음')
    # 3) 계산
    c_ok = sum(1 for n in calcs if n['status'] in ok)
    c_held = sum(1 for n in calcs if n['status'] not in ok)
    calc_txt = f"계산 단계 {len(calcs)}개 중 {c_ok}개 완료" + (f", {c_held}개는 자료가 모자라 보류했어요" if c_held else '') + '.'
    # 4) 검사 — 매매 지시 표현, 값 종류 표시, 기준 날짜
    trade = [rx for c, rx, t, _ in COMPILED if c == 'trade'][0]
    trade_hits = sum(1 for i in items if trade.search(i.get('text') or '') or trade.search(i.get('label') or ''))
    unlabeled = sum(1 for i in items if not i.get('tier'))
    cut = (doc.get('cutoff') or '')[:10]
    check_txt = ((f"숫자 {len(items)}개 모두 값 종류(확인·계산·추정)를 달았고" if items else "보여 드릴 숫자가 없어 지어내지 않고 「아직 모르는 것」으로 남겼고")
                 + f", 매매·추천 표현은 {trade_hits}건이에요. {cut} 장 마감 뒤에 나온 자료는 쓰지 않았어요.")
    # 5) 확인서
    receipt_txt = f"자료 지문(해시) {hashed}개를 담은 근거 확인서로 누구나 같은 결과가 나오는지 다시 계산해 볼 수 있어요."
    if repairs:
        receipt_txt += f" 이 답은 막힌 곳 {len(repairs)}곳을 고쳐 다시 조사한 결과예요."
    # 쉬운 화면의 카드·조립·계산은 AI 모델을 부르지 않는다. v0.26: AI 길잡이가 질문을 바꿔 줬으면 그 횟수만 정직하게 센다.
    gmeta = meta.get('guide') if isinstance(meta.get('guide'), dict) else {}
    model_calls = int(gmeta.get('calls') or 0)
    if model_calls:
        plan_txt += f" 질문은 AI 길잡이({gmeta.get('model') or '모델'})가 앱의 말로 바꿔 준 것을 사용자가 확인하고 실행했어요."
        agent_tech += ' · AI 길잡이: 질문 문장 바꾸기에만 쓰임(숫자·계산에 쓰지 않음, 바꾼 질문은 규칙 엔진이 다시 읽어 확인)'
    steps = [
        {'id': 'plan', 'title': '질문 이해', 'text': plan_txt, 'tech': agent_tech, 'tech_name': '근거 사슬' if card else '직접 구성' if manual else '에이전트', 'attrs': ['맞춤'] if (card or manual) else ['에이전트', '맞춤'],
         'state': 'ok'},
        {'id': 'find', 'title': '자료 찾기', 'text': find_txt, 'tech': find_tech, 'tech_name': 'RAG' if rag else '도구',
         'attrs': ['실시간', '전문'], 'state': 'ok' if t_ok == len(tools) else 'part'},
        {'id': 'calc', 'title': '계산', 'text': calc_txt, 'tech': '계산 단계 — 정해진 식과 규칙만 씀(같은 자료면 언제나 같은 값)', 'tech_name': '계산 규칙',
         'attrs': ['전문', '예측'] if any(i['tier'] == 'estimate' for i in items) else ['전문'], 'state': 'ok' if not c_held else 'part'},
        {'id': 'check', 'title': '검사', 'text': check_txt, 'tech': '근거 관문 — 값 종류 8가지를 섞지 않고, 매매 지시 표현 규칙 검사, 기준 날짜 뒤 자료 제외', 'tech_name': '관문',
         'attrs': ['교육', '개방'], 'state': 'ok' if not trade_hits and not unlabeled else 'part'},
        {'id': 'receipt', 'title': '확인서', 'text': receipt_txt,
         'tech': '재현 확인 — 같은 근거·같은 기준 날짜로 다시 계산해 단계별 지문 대조' + (' · 수리 에이전트가 막힌 곳마다 대체 방법을 제안하고, 사람이 고른 것만 다시 실행' if repairs else ''),
         'tech_name': '확인서 · 수리 에이전트' if repairs else '확인서',
         'attrs': ['재귀발전', '에이전트', '반응'] if repairs else ['재귀발전'], 'state': 'ok'},
    ]
    ai = ('AI 모델 호출 0회 — 이 답은 규칙과 계산만으로 만들었어요. 그래서 같은 질문이면 언제나 같은 답이 나와요.'
          if not model_calls else f'AI 모델 호출 {model_calls}회 — AI 길잡이가 질문을 앱의 말로 바꾸는 데만 썼어요. 숫자와 계산은 모두 규칙과 계산으로 만들었어요.')
    return {'steps': steps, 'model_calls': model_calls, 'ai_note': ai, 'llm_configured': _llm_configured(), 'planned_by': planned}


def card_status(card, company, cover, ledger=None, reported=None):
    """이 회사에 이 카드를 쓸 수 있는지와 그 이유 (근거 지도 개수표 기준). ledger: 승인된 증권사 전망이 있는 종목 집합."""
    if card.get('needs_ledger') and ledger is not None and company not in ledger:
        if reported is not None and company in reported:     # v0.37.6: 흐린 이유를 사실대로 — 받아 둔 보고서가 있는지로 나눈다
            return False, '이 회사 보고서는 받아 두었지만, 확인을 마친 실적 전망 숫자가 아직 없어요(사람 확인 대기이거나 매출·영업이익 표가 없는 서식). 전문가 모드 「증권사 전망」에서 볼 수 있어요.'
        return False, '보고서를 모으는 곳(네이버 증권 리서치)에 최근 이 회사 보고서가 올라오지 않아 보여 드릴 전망이 없어요. 전문가 모드 「증권사 전망」에서 직접 넣을 수 있어요.'
    if card.get('base_only') and company not in COMPANIES:
        return False, '수출 통계와 분기 매출을 함께 가진 회사(삼성전자·SK하이닉스)만 돼요.'
    miss = [k for k in card['needs'] if cover is not None and not (cover.get(k) or {}).get('n')]
    if miss:
        from .market import COVER_LABEL
        return False, '이 회사는 ' + ', '.join(COVER_LABEL.get(k, k) for k in miss) + ' 자료가 사본에 없어요.'
    return True, ''


def plan(card_id, company, cutoff='', rcept_no=''):
    """질문 카드 하나 → 고정된 근거 사슬(워크플로 문서). 질문을 잘못 알아듣는 일이 없다."""
    if card_id not in CARD:
        raise KeyError(card_id)
    base = company in COMPANIES
    N, E = [], []
    if card_id == 'events':
        N = [_n('t08', 'T08', company=company, lookback_days=180), _n('t06', 'T06', company=company, lookback=260), _n('n11', 'N11'), _n('n12', 'N12')]
        E = [_e('t08', 'events', 'n11', 'events'), _e('t08', 'events', 'n12', 'events'), _e('t06', 'prices', 'n12', 'prices')]
    elif card_id == 'price':
        N = [_n('t06', 'T06', company=company, lookback=260), _n('t07', 'T07', company=company, lookback=260),
             _n('n09', 'N09'), _n('n10', 'N10'), _n('n07', 'N07'), _n('n08', 'N08')]
        E = [_e('t06', 'prices', 'n09', 'prices'), _e('t06', 'prices', 'n10', 'prices'), _e('t07', 'flows', 'n07', 'flows'),
             _e('t06', 'prices', 'n08', 'prices'), _e('t07', 'flows', 'n08', 'flows'), _e('t06', 'prices', 'n07', 'prices')]
    elif card_id == 'earnings':
        if base:
            N = [_n('t01', 'T01'), _n('n01', 'N01', companies=[company], years=[2024, 2025], metrics=['revenue', 'operatingProfit', 'cfo', 'ppeAcquisition', 'intangibleAcquisition'])]
            E = [_e('t01', 'corpus', 'n01', 'corpus')]
        else:
            N = [_n('t11', 'T11', company=company), _n('n01', 'N01', companies=[], years=[2024, 2025], metrics=['revenue', 'operatingProfit', 'cfo', 'ppeAcquisition', 'intangibleAcquisition'])]
            E = [_e('t11', 'filings', 'n01', 'filings')]
        N += [_n('t14', 'T14', company=company), _n('n19', 'N19')]; E.append(_e('t14', 'segments', 'n19', 'segments'))   # v0.37 사업부별 분기 매출
    elif card_id == 'macro':
        N = [_n('t10', 'T10'), _n('n05', 'N05'), _n('n06', 'N06')]
        E = [_e('n05', 'exposure', 'n06', 'exposure'), _e('t10', 'macro', 'n06', 'macro')]
        if base:
            N.insert(0, _n('t01', 'T01')); E.append(_e('t01', 'corpus', 'n05', 'corpus'))
            N.insert(0, _n('t11', 'T11', company=company)); E.append(_e('t11', 'filings', 'n05', 'filings'))   # v0.37.7 기준 기업도 T11로 노출 등급
        else:
            N.insert(0, _n('t11', 'T11', company=company)); E.append(_e('t11', 'filings', 'n05', 'filings'))
    elif card_id == 'holders':
        N = [_n('t12', 'T12', company=company), _n('n13', 'N13')]
        E = [_e('t12', 'ownership', 'n13', 'ownership')]
        if base:
            N.insert(1, _n('t02', 'T02', company=company, preset='holders', k=10)); E.append(_e('t02', 'docs', 'n13', 'docs'))
    elif card_id == 'relations':
        N = [_n('t06', 'T06', company=company, lookback=1300), _n('t10', 'T10'), _n('n15', 'N15')]
        E = [_e('t06', 'prices', 'n15', 'prices'), _e('t10', 'macro', 'n15', 'macro')]
    elif card_id == 'forecasts':
        N = [_n('t13', 'T13', company=company), _n('t11', 'T11', company=company), _n('n16', 'N16')]
        E = [_e('t13', 'ledger', 'n16', 'ledger'), _e('t11', 'filings', 'n16', 'filings')]
    elif card_id == 'edi':
        N = [_n('t06', 'T06', company=company, lookback=1300), _n('t11', 'T11', company=company), _n('t13', 'T13', company=company), _n('n17', 'N17'), _n('n18', 'N18')]
        E = [_e('t06', 'prices', 'n17', 'prices'), _e('t11', 'filings', 'n17', 'filings'), _e('t13', 'ledger', 'n17', 'ledger'),
             _e('t06', 'prices', 'n18', 'prices'), _e('t11', 'filings', 'n18', 'filings')]
    elif card_id == 'nowcast':
        N = [_n('t11', 'T11', company=company), _n('t10', 'T10'), _n('n14', 'N14')]
        E = [_e('t11', 'filings', 'n14', 'filings'), _e('t10', 'macro', 'n14', 'macro')]
    elif card_id == 'filing':                                          # v0.38 T1
        N = [_n('t15', 'T15', company=company, rcept_no=rcept_no), _n('t06', 'T06', company=company, lookback=1300), _n('n20', 'N20')]
        E = [_e('t15', 'filing', 'n20', 'filing'), _e('t06', 'prices', 'n20', 'prices')]
    outs = [n['id'] for n in N if n['type'].startswith('N')]
    N.append(_n('t05', 'T05'))
    E += [_e(o, 'facts' if o == 'n01' else 'exposure' if o == 'n05' else 'finding', 't05', 'results') for o in outs]
    N, E = _lay(N, E)
    name = f"{CARD[card_id]['title']} — {company}"
    meta = {'card': card_id, 'company': company, 'ui': 'easy'}
    if card_id == 'filing':
        meta['rcept_no'] = rcept_no                                   # 다른 카드의 meta(확인서 사슬)는 그대로
    return {'name': name[:100], 'cutoff': cutoff or '', 'nodes': N, 'edges': E, 'meta': meta}


# ---------------------------------------------------------------- 답 카드
def _item(node_id, node_type, label, text, kind, formula=None, value=None, unit=None, source=None):
    kind = kind if kind in KINDS else 'derived'
    return {'node': node_id, 'node_type': node_type, 'node_name': SPECS[node_type]['display_name'], 'label': label, 'text': text,
            'kind': kind, 'kind_label': KINDS[kind], 'tier': TIER[kind], 'tier_label': TIER_LABEL[TIER[kind]],
            'formula': formula, 'value': value, 'unit': unit, 'source': source}


HOW = {'manual': '접수번호로 직접 받음', 'bulk': '대량 받기로 받음', 'auto': '자동 확인이 받음'}           # v0.38 T2-4d 출처 표시
USE = {'official': '공식 공개 자료(출처를 밝혀 인용)', 'public': '공공데이터 — 이용 조건(상업적 이용·재배포) 확인 전',
       'portal': '포털 수집 — 연구용 한정(공개판에서 뺌)', 'unofficial': '비공식 — 참고용', 'rule_derived': '앱이 규칙으로 계산한 값',
       'derived': '앱이 계산한 값', 'registered': '등록 정보'}
TRADE_STATUS_NOTE = '거래 상태(거래정지·관리종목·투자경고 등)는 아직 자료로 받지 않아 이 답에 표시하지 않아요.'


def _kst(t):
    """ISO 시각 → 「2026-11-12 14:05 (한국 시각)」. 읽지 못하면 받은 글자 그대로."""
    from datetime import datetime, timedelta, timezone
    try:
        d = datetime.fromisoformat(str(t).replace('Z', '+00:00'))
    except ValueError:
        return str(t)
    if d.tzinfo is None:
        return d.strftime('%Y-%m-%d %H:%M')
    return d.astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M') + ' (한국 시각)'


def _prov(e, s):
    """v0.38 T2-4d: 언제·어떻게 왔나(detail)와 이용 범위(use)를 더한다. 원래 칸은 그대로. 기록이 없는 것은 「기록 없음」으로 — 지어내지 않는다."""
    e['use'] = USE.get(str(e.get('grade') or '').split(':')[0], '이용 범위 확인 전')
    d = []
    if s.get('rcept_no'):
        e['rcept_no'], e['url'] = s['rcept_no'], s.get('url')
        d.append(f"DART 접수번호 {s['rcept_no']}")
        if s.get('fetched_at'):
            d.append(f"원문을 받은 시각 {_kst(s['fetched_at'])} · {HOW.get(s.get('how'), '받은 방법 기록 없음')}")
    if s.get('collected_at_max'):
        d.append(f"자료를 모은 시각(가장 늦은 줄) {_kst(s['collected_at_max'])}")
    e['detail'] = d
    return e


def _seen_line(info):
    """J23: 앱이 공시 목록에서 처음 본 시각(자동 확인 기록) 한 줄. 단계 결과가 아니라 답을 보일 때 붙인다."""
    if not info or not info.get('first_seen_at'):
        return '앱이 공시 목록에서 처음 본 시각: 기록 없음(자동 확인 기록이 없는 공시)'
    t = f"앱이 공시 목록에서 처음 본 시각 {_kst(info['first_seen_at'])}"
    if info.get('first_check'):
        return t + ' — 관심 종목에 넣은 뒤 첫 확인 때 본 것이라 실제로 공시가 뜬 때보다 늦을 수 있어요'
    if info.get('prev_checked_at'):
        return t + f" — 그 직전 확인은 {_kst(info['prev_checked_at'])}, 공시는 그 사이에 목록에 올라왔어요"
    return t


def _sources(p):
    out = []
    for k in ('price_source', 'flow_source', 'peer_source', 'macro_source', 'event_source', 'owner_source', 'index_source', 'segment_source', 'filing_source'):
        v = p.get(k)
        if isinstance(v, dict):
            for name, s in (v.items() if all(isinstance(x, dict) for x in v.values()) else [(k, v)]):
                if isinstance(s, dict) and (s.get('snapshot') or s.get('sha256')):
                    out.append(_prov({'what': s.get('origin') or name, 'snapshot': s.get('snapshot'), 'sha256': s.get('sha256'), 'grade': s.get('source_grade'), 'file': s.get('file')}, s))
    if p.get('doc_source'):
        out.append(_prov({'what': '사업보고서 원문 색인', 'snapshot': None, 'sha256': (p['doc_source'].get('index') or {}).get('corpusHash'), 'grade': 'official'}, {}))
    return out


import re as _re


def plain(t):
    """쉬운 화면용: 단계 코드(T08·N11)를 이름으로, 개발 용어를 쉬운 말로."""
    if not isinstance(t, str):
        return t
    t = _re.sub(r'\b([TN]\d{2})\b', lambda m: f"「{SPECS[m.group(1)]['display_name']}」" if m.group(1) in SPECS else m.group(1), t)
    return t.replace('노드', '단계').replace('미연결', '함께 보지 않음').replace('패킷', '결과')


def _won(v, unit):
    """백만원 → 「1조 2,345억 원」처럼 읽기 쉬운 말. 원래 값은 근거 서랍에 그대로 남는다."""
    try:
        x = float(str(v).replace(',', ''))
    except ValueError:
        return f'{v} {unit}'
    if unit != '백만원':
        return f'{x:,.0f} {unit}'
    eok = x / 100
    sign = '-' if eok < 0 else ''
    eok = abs(eok)
    jo, rest = int(eok // 10000), eok % 10000
    if jo:
        return f"{sign}{jo:,}조 {rest:,.0f}억 원" if round(rest) else f'{sign}{jo:,}조 원'
    return f'{sign}{eok:,.0f}억 원' if eok >= 1 else f'{sign}{x:,.0f}백만 원'


def answer(run, get_packet, name_of=None, seen=None):
    """실행 결과 → 답 카드. get_packet(pid) → packet."""
    doc = run['doc']
    easy = doc.get('meta') or {}
    company = easy.get('company')
    items, unknown, notices, sources, tables, limits, relmap, fcast = [], [], [], [], [], [], None, None
    st = {n['node_id']: n for n in run['nodes']}
    name = None
    edi_view = None                                       # v0.37.2: 주가·V 그림용 기록
    through = {}                                          # v0.28.2: 가격·수급 자료의 마지막 거래일
    for n in run['nodes']:
        if n['node_type'] in ('T06', 'T07') and n.get('output_packet') and n['status'] in ('succeeded', 'partial'):
            try:
                rows = (get_packet(n['output_packet'])['payload'].get('rows') or [])
                if rows:
                    k = '가격' if n['node_type'] == 'T06' else '수급'
                    through[k] = max(through.get(k, ''), str(rows[-1]['trade_date'])[:10])
            except Exception:
                pass
    for n in run['nodes']:
        t = n['node_type']
        if not t.startswith('N'):
            if n['status'] in ('held', 'failed', 'blocked') and n['reason']:
                unknown.append({'node': n['node_id'], 'node_name': SPECS[t]['display_name'], 'text': n['reason']})
            continue
        if not n['output_packet']:
            unknown.append({'node': n['node_id'], 'node_name': SPECS[t]['display_name'], 'text': n['reason'] or '결과 없음'})
            continue
        pk = get_packet(n['output_packet'])
        p = pk['payload']
        name = name or p.get('name')
        if n['status'] in ('held', 'failed'):
            unknown.append({'node': n['node_id'], 'node_name': SPECS[t]['display_name'], 'text': n['reason']})
        for f in p.get('findings', []) or []:
            if not f.get('claim'):
                continue
            items.append(_item(n['node_id'], t, f.get('name') or SPECS[t]['display_name'], f['claim'], f.get('kind', 'derived'),
                               f.get('formula'), f.get('value'), f.get('unit'),
                               f['source'] if isinstance(f.get('source'), dict) and f['source'].get('url') else None))   # v0.36.4: 원문 링크가 있는 줄만
        if t == 'N01':
            for fct in sorted(p.get('facts', []), key=lambda f: -int(f['period'])):
                sc = {'CFS': '연결', 'OFS': '별도'}.get(fct['scope'], fct['scope'])
                items.append(_item(n['node_id'], t, f"{fct['company_name']} {fct['period']}년 {fct['metric_label']}", f"{_won(fct['value'], fct['unit'])} ({sc})",
                                   'fact_official', None, fct['value'], fct['unit'],
                                   {'title': fct['source'].get('title'), 'url': fct['source'].get('url'), 'status': fct.get('status')}))
            cname = {f['company']: f['company_name'] for f in p.get('facts', []) if f.get('company') and f.get('company_name')}
            for d in p.get('derived', []):
                who = cname.get(d.get('company')) or COMPANIES.get(d.get('company')) or ''
                val = _won(d['value'], d['unit']) if d['unit'] == '백만원' else f"{d['value']} {d['unit']}"
                items.append(_item(n['node_id'], t, f"{who} {d['period']}년 {d['label']}".strip(), val, 'derived', d['formula'], d['value'], d['unit']))
            for m in p.get('missing', []):
                unknown.append({'node': n['node_id'], 'node_name': SPECS[t]['display_name'], 'text': f"{m['period']}년 {m['metric']}: {m['reason']}"})
        if t == 'N05' and not p.get('findings'):
            for e in p.get('exposures', []):
                items.append(_item(n['node_id'], t, f"{e['name']} 공시 민감도", f"환율: {e.get('fx_scenario')} / 금리: {e.get('rate_scenario')}", 'fact_official'))
        for h in p.get('held', []) or []:
            if '하지 않음' in h or '않습니다' in h or '평가가 아' in h:
                limits.append(h)                         # 앱이 일부러 하지 않는 것 — 모르는 것과 구분
            else:
                unknown.append({'node': n['node_id'], 'node_name': SPECS[t]['display_name'], 'text': h})
        if t == 'N16' and p.get('trends'):
            fcast = {'company': p.get('company'), 'trends': p['trends'], 'versus_actual': p.get('versus_actual') or [], 'unit': '백만원', 'notice': p.get('notice'),
                     'quarters': p.get('quarter_scorecard'),
                     'reports': [{k: r.get(k) for k in ('broker', 'report_date', 'title')} for r in (p.get('reports') or [])]}
        if t == 'N17' and p.get('series'):
            from .edi import METHODS as _EM
            edi_view = {'as_of': p.get('as_of'), 'unit': '원', 'methods': [{'key': k, 'label': l} for k, l in _EM], 'series': p['series'],
                        'assumptions': p.get('assumptions'), 'notice': p.get('notice')}
        if t == 'N15' and p.get('relations'):
            relmap = {'months': p.get('months'), 'notice': p.get('notice'),
                      'rows': [{'factor': r['factor'], 'name': r['factor_name'], 'grade': r['grade'], 'grade_label': r['grade_label'],
                                'r': r.get('r'), 'ci': r.get('ci_adjusted'), 'lag': r.get('best_lag'), 'n': r.get('n'),
                                'halves': r.get('halves'), 'oos': r.get('oos'), 'known_before': r.get('known_before'), 'change': r.get('change')}
                               for r in p['relations']]}
        if p.get('notice'):
            notices.append(p['notice'])
        for tb in p.get('tables', []) or []:
            tables.append({'node': n['node_id'], 'node_name': SPECS[t]['display_name'], **tb})
        sources += _sources(p)
    if company and not name:
        name = COMPANIES.get(company) or (name_of(company) if name_of else None)
    count = {k: sum(1 for i in items if i['tier'] == k) for k in TIER_LABEL}
    card = CARD.get(easy.get('card') or '') or easy.get('my_card') or {}      # v0.36
    # 맨 위 문장: 결론이 아니라 정리
    head = (f"{name or company or ''} — {card.get('title', '조사 결과')} "
            f"자료로 확인 {count['fact']}건 · 계산 {count['calc']}건 · 추정·가정 {count['estimate']}건 · 아직 모르는 것 {len(unknown)}건").strip()
    key = []
    no = len(card.get('outputs', [])) or 2
    per = {1: 4, 2: 2}.get(no, 1)
    order = {'estimate': 0, 'fact': 1, 'calc': 2}
    if easy.get('card') == 'filing':                     # v0.38 T2-4d PM 결정 ③: 공시 숫자 화면만 사실 → 계산 → 추정
        order = {'fact': 0, 'calc': 1, 'estimate': 2}
        items.sort(key=lambda i: order[i['tier']])
    by_node = {}
    for i in items:
        by_node.setdefault(i['node'], []).append(i)
    for nid in [o for o in card.get('outputs', [])] + [x for x in by_node if x not in card.get('outputs', [])]:
        rs = sorted(by_node.get(nid, []), key=lambda i: order[i['tier']])     # 추정값이 있으면 먼저(숨기지 않기 위해)
        key += rs[:per]
    key = key[:4]
    uniq = []
    for s in sources:
        if s not in uniq:
            uniq.append(s)
    if seen is not None:                                  # v0.38 T2-4d (J23): seen(접수번호) → 앱이 처음 본 기록. 답을 보일 때만 붙임
        for s in uniq:
            if s.get('rcept_no'):
                s['detail'] = list(s.get('detail') or []) + [_seen_line(seen(s['rcept_no']))]
    for i in items:
        i['label'], i['text'], i['formula'] = plain(i['label']), plain(i['text']), plain(i['formula'])
    for u in unknown:
        u['text'] = plain(u['text'])
    for u in unknown:
        u['id'] = hold_id(company, st[u['node']]['node_type'] if u['node'] in st else '', u['text'])
    held_steps = [{'id': hold_id(company, n['node_type'], plain(n['reason'])), 'node': n['node_id'], 'node_type': n['node_type'], 'node_name': SPECS[n['node_type']]['display_name'],
                   'status': n['status'], 'code': n.get('error_code'), 'text': plain(n['reason'])}
                  for n in run['nodes'] if n['status'] in ('partial', 'held', 'failed', 'blocked') and n.get('reason')]
    limits = [plain(x) for x in limits]
    notices = [plain(x) for x in notices]
    return {'run_id': run['id'], 'status': run['status'], 'cutoff': doc.get('cutoff'), 'card': easy.get('card'), 'card_title': card.get('title'),
            'company': company, 'name': name, 'headline': head, 'count': count, 'key': key, 'items': items, 'unknown': unknown, 'held': held_steps,
            'notices': list(dict.fromkeys(notices)), 'limits': list(dict.fromkeys(limits)), 'not_this': NOT_THIS,
            'relmap': relmap, 'forecast': fcast, 'edi': edi_view, 'data_through': through, 'view': card.get('view'), 'repairs': easy.get('repairs') or [], 'repaired_from': easy.get('repaired_from'), 'tables': tables, 'sources': uniq, 'source_notes': [TRADE_STATUS_NOTE],
            'nodes': [{'id': n['node_id'], 'type': n['node_type'], 'name': SPECS[n['node_type']]['display_name'], 'status': n['status']} for n in run['nodes']],
            'process': process(run, get_packet, items, unknown, uniq, easy.get('repairs') or []),
            'next': [{'id': x, 'title': CARD[x]['title']} for x in card.get('next', []) if x in CARD], 'group': card.get('group'), 'kind': card.get('kind'),
            'expert': {'hints': list(card.get('expert') or ['질문 속 낱말로 고른 단계를 그림으로 보고, 단계를 더하거나 빼서 다시 계산']),
                       'stuck': sum(1 for n in run['nodes'] if n['status'] not in ('succeeded', 'partial'))}}


# ---------------------------------------------------------------- 근거 확인서 (C2, 파일 형식 id는 modu-research-receipt/1 그대로)
def _canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def receipt(run, get_packet):
    """같은 사슬·같은 기준시점·같은 사본이면 누가 다시 돌려도 같은 결과 해시가 나온다는 증명서."""
    doc = run['doc']
    chain = {'nodes': [{'id': n['id'], 'type': n['type'], 'config': n.get('config', {})} for n in doc['nodes']],
             'edges': [{k: e[k] for k in ('from_node', 'from_port', 'to_node', 'to_port')} for e in doc['edges']]}
    rows = []
    for n in run['nodes']:
        if n['node_type'] == 'T05':          # 취합은 실행 번호가 든 묶음이라 대조에서 뺀다(새 숫자를 만들지 않음)
            continue
        dg = None
        if n['output_packet']:
            dg = get_packet(n['output_packet'])['header']['payload_digest']
        rows.append({'node': n['node_id'], 'type': n['node_type'], 'name': SPECS[n['node_type']]['display_name'], 'status': n['status'], 'payload_digest': dg})
    body = {'format': 'modu-research-receipt/1', 'cutoff': doc.get('cutoff'), 'chain_digest': hashlib.sha256(_canon(chain).encode()).hexdigest(),
            'results': rows, 'repairs': (doc.get('meta') or {}).get('repairs') or []}
    rid = hashlib.sha256(_canon(body).encode()).hexdigest()
    return {**body, 'receipt_id': rid, 'run_id': run['id'], 'chain': chain, 'meta': doc.get('meta'), 'name': doc.get('name'),
            'how_to_verify': '같은 앱·같은 사본에서 「확인서로 다시 계산해 보기」에 이 파일을 넣으면 같은 사슬을 같은 기준시점으로 다시 계산해 결과 해시를 하나씩 대조합니다.',
            'not_this': NOT_THIS}


def verify(rc, rerun):
    """rerun(doc) → 새 실행. 결과 해시를 노드별로 대조한다."""
    chain = rc['chain']
    if hashlib.sha256(_canon(chain).encode()).hexdigest() != rc['chain_digest']:
        return {'ok': False, 'reason': '확인서 안의 사슬이 사슬 해시와 다릅니다(확인서가 고쳐졌을 수 있음).', 'rows': []}
    body = {k: rc[k] for k in ('format', 'cutoff', 'chain_digest', 'results')} | {'repairs': rc.get('repairs') or []}
    if hashlib.sha256(_canon(body).encode()).hexdigest() != rc['receipt_id']:
        return {'ok': False, 'reason': '확인 번호가 내용과 맞지 않습니다(확인서가 고쳐졌을 수 있음).', 'rows': []}
    doc = {'name': rc.get('name') or '근거 확인서 검증', 'cutoff': rc['cutoff'],
           'nodes': [{**n, 'x': 0, 'y': 0} for n in chain['nodes']], 'edges': chain['edges'], 'meta': rc.get('meta') or {}}
    new = rerun(doc)
    rows = []
    for r in rc['results']:
        m = new.get(r['node'])
        rows.append({'node': r['node'], 'name': r['name'], 'then': r['payload_digest'], 'now': m, 'match': m == r['payload_digest']})
    ok = all(r['match'] for r in rows)
    return {'ok': ok, 'matched': sum(r['match'] for r in rows), 'total': len(rows), 'rows': rows,
            'reason': '다시 계산해도 똑같이 나왔어요 — 같은 근거로 같은 결과가 다시 나왔습니다.' if ok else
            '다른 결과가 있습니다. 사본(자료)이 바뀌었거나 앱 버전이 다를 수 있습니다.'}
