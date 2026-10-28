"""Persona-specific presentation for the two Agents, without an LLM.

A persona changes only the order of sections, the detail level, glossary entries and follow-up questions.
Every persona sees the same sections, claims, numbers, evidence and withheld status: style A puts
opportunity sections first and style C puts risk sections first, but neither drops the other side.
"""
from sh_agents.personas import LEVEL_DEFINITIONS, STYLE_DEFINITIONS, InvestmentStyle, LiteracyLevel

PRESENTATION_VERSION = '1.0'

SECTIONS = {
    'industry_business_model': {
        'summary': '사업 요약',
        'opportunity': '기회 요인(성립 조건)',
        'risk': '위험 요인(하방 조건)',
        'competition': '경쟁 5요인 후보 발췌',
        'evidence': '근거 원문 위치',
        'gaps': '자료 공백·한계',
    },
    'technical_analysis': {
        'summary': '현재 상태 요약',
        'trend': '추세: 종가와 이동평균 비교',
        'return': '직전 대비 수익률',
        'volatility': '변동성',
        'volume': '거래량 변화',
        'quality': '데이터 품질·가격 검사',
        'method': '산식·관측 개수·조정 기준',
        'gaps': '한계',
    },
}

# Base order per style. U is the neutral canonical order.
STYLE_ORDER = {
    'industry_business_model': {
        'A': ['summary', 'opportunity', 'competition', 'risk', 'evidence', 'gaps'],
        'C': ['summary', 'risk', 'gaps', 'competition', 'opportunity', 'evidence'],
        'U': ['summary', 'opportunity', 'risk', 'competition', 'evidence', 'gaps'],
    },
    'technical_analysis': {
        'A': ['summary', 'trend', 'return', 'volume', 'volatility', 'quality', 'method', 'gaps'],
        'C': ['summary', 'volatility', 'quality', 'volume', 'trend', 'return', 'method', 'gaps'],
        'U': ['summary', 'trend', 'return', 'volatility', 'volume', 'quality', 'method', 'gaps'],
    },
}

# Higher literacy moves method/source sections forward; L1 keeps them last.
LEVEL_PROMOTE = {
    'industry_business_model': {'L1': [], 'L2': [], 'L3': ['competition'], 'L4': ['evidence', 'gaps']},
    'technical_analysis': {'L1': [], 'L2': [], 'L3': ['quality'], 'L4': ['method', 'quality']},
}

DETAIL = {
    'L1': {'name': 'brief', 'maxClaims': 3, 'showFormula': False, 'showEvidenceLocation': False,
           'glossary': True, 'comparisonTable': False},
    'L2': {'name': 'standard', 'maxClaims': 5, 'showFormula': False, 'showEvidenceLocation': True,
           'glossary': True, 'comparisonTable': False},
    'L3': {'name': 'comparative', 'maxClaims': 10, 'showFormula': True, 'showEvidenceLocation': True,
           'glossary': False, 'comparisonTable': True},
    'L4': {'name': 'methodological', 'maxClaims': None, 'showFormula': True, 'showEvidenceLocation': True,
           'glossary': False, 'comparisonTable': True},
}

GLOSSARY = {
    'industry_business_model': {
        '사업보고서': '회사가 1년에 한 번 금융감독원(DART)에 내는 공식 보고서입니다.',
        '사업의 내용': '사업보고서에서 회사가 무엇을 팔고 어떻게 돈을 버는지 설명하는 장입니다.',
        '매출 구조': '어떤 제품·지역·고객에서 매출이 나오는지의 구성입니다.',
        '진입 장벽': '새 경쟁자가 시장에 들어오기 어렵게 만드는 요인(특허·규제·설비 등)입니다.',
        '교섭력': '고객이나 공급자가 가격·조건을 자기에게 유리하게 정할 수 있는 힘입니다.',
        '원문 발췌': 'DB에 저장된 공시 본문 일부입니다. 내용이 주장을 지지하는지는 사람이 확인합니다.',
    },
    'technical_analysis': {
        '이동평균(SMA)': '최근 N개 종가의 평균입니다. N은 달력일이 아니라 관측 개수입니다.',
        '수익률': '직전 종가 대비 마지막 종가의 변화 비율입니다.',
        '변동성': '수익률이 흩어진 정도(표준편차)입니다. 여기서는 연율화하지 않았습니다.',
        '거래량 변화': '마지막 거래량을 직전 N개 평균과 비교한 비율입니다.',
        '수정주가': '액면분할 등 기업행위를 반영해 과거 가격을 조정한 가격입니다.',
        '가격제한폭': '하루에 움직일 수 있는 가격 범위입니다(국내 ±30%).',
    },
}

QUESTIONS = {
    'industry_business_model': {
        'A': ['이 기회가 성립하려면 어떤 조건이 계속 유지되어야 하나요?',
              '이 가설이 틀렸다고 판단할 근거(실패 조건)는 무엇인가요?'],
        'C': ['가장 큰 의존 위험(고객·원재료·규제)은 무엇이고 원문 근거가 있나요?',
              '위험을 완화하는 근거는 원문에서 확인되나요?'],
        'U': ['기회와 위험 각각의 원문 근거가 충분한가요?'],
    },
    'technical_analysis': {
        'A': ['추세가 유지된다고 볼 수 있는 조건과 깨지는 조건은 무엇인가요?',
              '거래량 변화가 가격 움직임과 같은 방향인가요?'],
        'C': ['변동성이 커진 구간과 데이터 품질 경고가 겹치나요?',
              '가격 조정 기준·기업행위 대조가 끝났나요?'],
        'U': ['추세·변동성·거래량이 같은 방향을 가리키나요?'],
    },
}
LEVEL_QUESTIONS = {
    'L1': '모르는 용어가 있으면 용어 풀이를 먼저 확인하세요.',
    'L2': '각 수치가 어떤 원문·계산에서 나왔는지 근거 ID로 확인하세요.',
    'L3': '반대 해석이 가능한 근거가 있는지 비교표로 확인하세요.',
    'L4': '산식·기간·조정 기준을 바꾸면 결론이 달라지는지(민감도) 검토하세요.',
}

# Calculation display order follows the section order of the matching section.
CALC_SECTION = {'TECH_SMA': 'trend', 'TECH_RETURN': 'return', 'TECH_VOLATILITY': 'volatility',
                'TECH_VOLUME_CHANGE': 'volume'}


def _order(domain, level, style):
    order = list(STYLE_ORDER[domain][style])
    promote = LEVEL_PROMOTE[domain][level]
    # Keep summary first, then promoted sections, then the remaining style order.
    head = ['summary'] + [s for s in promote if s != 'summary']
    return head + [s for s in order if s not in head]


def build_presentation(result, literacy='L2', style='U'):
    """Return the presentation plan for an Agent result. Does not read or change any values."""
    domain = result['agentType']
    if domain not in SECTIONS:
        raise ValueError('Unsupported domain')
    level, style = LiteracyLevel(literacy).value, style if style == 'U' else InvestmentStyle(style).value
    order = _order(domain, level, style)
    detail = DETAIL[level]
    calc_ids = [c['calculationId'] for c in result.get('calculations', [])]
    calc_order = sorted(calc_ids, key=lambda cid: order.index(CALC_SECTION[cid])
                        if CALC_SECTION.get(cid) in order else len(order))
    claim_ids = [c['claimId'] for c in result.get('claims', [])]
    limit = detail['maxClaims']
    shown = claim_ids if limit is None else claim_ids[:limit]
    withheld = result.get('status') == 'withheld'
    return {
        'presentationVersion': PRESENTATION_VERSION,
        'personaId': f'{level}-{style}',
        'literacy': {'code': level, 'name': LEVEL_DEFINITIONS[LiteracyLevel(level)]['name']},
        'style': {'code': style, 'name': STYLE_DEFINITIONS[InvestmentStyle(style)]['name'] if style != 'U'
                  else '중립(미확정)'},
        'sections': [{'key': k, 'title': SECTIONS[domain][k]} for k in order],
        'detail': detail['name'],
        'showFormula': detail['showFormula'],
        'showEvidenceLocation': detail['showEvidenceLocation'],
        'comparisonTable': detail['comparisonTable'],
        'calculationOrder': calc_order,
        'claimsShown': shown,
        'claimsHiddenCount': len(claim_ids) - len(shown),  # 상세도 차이일 뿐 삭제가 아님
        'glossary': [{'term': t, 'explanation': e} for t, e in GLOSSARY[domain].items()]
        if detail['glossary'] else [],
        'checkQuestions': QUESTIONS[domain][style] + [LEVEL_QUESTIONS[level]],
        'withheldNotice': '자료 부족·품질 문제로 판단을 보류했습니다. 보류 사유를 먼저 확인하세요.'
        if withheld else None,
        'invariants': '수치·근거·보류 판정은 모든 페르소나에 동일합니다. 매수·매도 추천이 아닙니다.',
    }


def compare_personas(result):
    """Rows for the 8 combined personas plus neutral, for notebook comparison tables."""
    rows = []
    for level in ['L1', 'L2', 'L3', 'L4']:
        for style in ['A', 'C', 'U']:
            p = build_presentation(result, level, style)
            rows.append({'페르소나': p['personaId'], '이해도': p['literacy']['name'], '성향': p['style']['name'],
                         '상세도': p['detail'], '제시 순서': ' → '.join(s['title'] for s in p['sections']),
                         '용어 풀이': len(p['glossary']), '표시 주장 수': len(p['claimsShown']),
                         '확인 질문': ' / '.join(p['checkQuestions'])})
    return rows
