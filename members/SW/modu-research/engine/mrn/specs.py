"""Node registry. Roles follow the 2026-11-02 basic/extension agreement
(2차_실제/modu-research-orchestrated/docs/basic-extension-agreement.md).

implementation: real | partial | not_connected — always shown to the user.
"""

PERSPECTIVES = [
    ('fundamentals', '기업가치·실적'),
    ('industry', '산업·경쟁'),
    ('macro', '거시·정책'),
    ('flow', '수급'),
    ('technical', '기술적 분석'),
    ('sentiment', '투자심리·뉴스'),
]
PERSPECTIVE_IDS = [p for p, _ in PERSPECTIVES]

# Item kinds used in valuation inputs and findings (prompt §8).
KINDS = {
    'fact_official': '공식 원문 확인 사실',
    'forecast_external': '증권사 외부 전망',
    'forecast_model': '모델 자체 전망',
    'assumption_user': '사용자 가정',
    'assumption_illustrative': '학습용 예시 가정 (실제 추정 아님)',
    'derived': '계산 파생값',
    'fact_portal': '포털 수집 사실 (공식 대조 전)',
    'rule_derived': '규칙·모델 산출값 (판단 아님)',
}

PORT_TYPES = {
    'OfficialCorpus': '공식 원문 묶음',
    'FactPackage': '확인된 과거 사실 패키지',
    'MacroExposure': '거시 관측·기업 노출',
    'AssumptionSet': '사용자 가정',
    'BrokerForecastPackage': '승인된 증권사 전망',
    'ValuationResult': '가치평가 결과',
    'PriceSeries': '가격·거래량 시계열',
    'FlowSeries': '투자자별 수급',
    'NewsEvents': '뉴스·사건',
    'IndustryPeers': '산업·비교기업 자료',
    'MacroSeries': '거시 지표 시계열',
    'CompanyFilings': '회사 공시 재무·민감도',
    'DocPassages': '사업보고서 원문 문단',
    'OwnershipData': '지분·대주주 공시',
    'SegmentRevenue': '사업부별 매출 (정기보고서 주석)',
    'FilingDoc': '공시 원문 1건 (DART, 읽은 칸 값)',
    'ForecastLedger': '승인된 증권사 전망 원장',
    'NodeFinding': '분석 결과',
    'Report': '보고서',
    'Any': '모든 결과',
}

COMPANIES = {'005930': '삼성전자', '000660': 'SK하이닉스'}
FACT_METRICS = {
    'revenue': '매출액', 'operatingProfit': '영업이익', 'cfo': '영업활동현금흐름',
    'currentAssets': '유동자산', 'currentLiabilities': '유동부채', 'assets': '자산총계',
    'liabilities': '부채총계', 'equity': '자본총계', 'inventory': '재고자산',
    'ppeAcquisition': '유형자산 취득', 'intangibleAcquisition': '무형자산 취득',
}


def port(name, type_, required=True, multiple=False, label=None, auto=False):
    """auto=True: 선택 입력이지만 조사 계획·조립 에이전트가 기본으로 이어 주는 입력."""
    return {'name': name, 'type': type_, 'required': required, 'multiple': multiple, 'label': label or PORT_TYPES.get(type_, type_), 'auto': auto}


def spec(id_, name, perspective, tier, implementation, description, inputs, outputs,
         config=None, sources=None, reason=None, reuse=None):
    return {
        'id': id_, 'display_name': name, 'version': '0.1.0', 'perspective': perspective,
        'tier': tier, 'implementation': implementation, 'description': description,
        'inputs': inputs, 'outputs': outputs, 'config_schema': config or {},
        'data_sources': sources or [], 'not_connected_reason': reason, 'reuse_origin': reuse,
    }


OFFICIAL_SOURCES = [
    {'id': 'dart-005930-2025-cfs', 'provider': 'DART (금융감독원)', 'scope': '삼성전자 2025 사업보고서 연결재무제표 (접수 20260310002820)',
     'as_of': '2026-03-10', 'collected_at': '2026-10-27', 'rights_status': 'public_official'},
    {'id': 'dart-000660-2025-cfs', 'provider': 'DART (금융감독원)', 'scope': 'SK하이닉스 2025 사업보고서 연결재무제표 (접수 20260317000635)',
     'as_of': '2026-03-17', 'collected_at': '2026-10-27', 'rights_status': 'public_official'},
    {'id': 'bok-base-rate', 'provider': '한국은행', 'scope': '기준금리 변경 이력', 'as_of': '2025-12-31',
     'collected_at': '2026-10-29', 'rights_status': 'public_official'},
    {'id': 'fed-h10-krw', 'provider': '미 연준 H.10', 'scope': '원/달러 일별 뉴욕 정오 매입률 (한국 종가 아님)', 'as_of': '2025-12-31',
     'collected_at': '2026-10-29', 'rights_status': 'public_official'},
]

REUSE_4373 = '2차_실제/modu-research-n01-unified (vendor/*, af/valuation.py) — reused/ORIGIN-sha256.txt'

ASSUMPTION_TEMPLATE_HINT = '방법별 가정(JSON). 오른쪽 "방법별 빈 양식" 또는 "학습용 예시"를 눌러 채우세요.'

REGISTRY = [
    # ---- common tools -------------------------------------------------
    spec('T01', '공식 원문 원천', 'common', 'tool', 'real',
         '저장된 공식 원문(DART 사업보고서 표·한국은행·연준 H.10)을 실행할 때마다 파일 해시와 표 셀 배열로 다시 대조해 묶음을 만든다.',
         [], [port('corpus', 'OfficialCorpus')],
         {'cutoff': {'type': 'datetime', 'label': '기준시점 (비우면 워크플로 기준시점)', 'default': ''}},
         OFFICIAL_SOURCES, reuse=REUSE_4373),
    spec('T03', '사용자 가정 입력', 'common', 'tool', 'real',
         '가치평가에 쓸 가정을 사람이 직접 입력한다. 빈 값을 자동 추정하지 않는다.',
         [], [port('assumptions', 'AssumptionSet')],
         {'method': {'type': 'enum', 'label': '가치평가 방법', 'options': ['dcf', 'ddm', 'rim', 'nav'], 'default': 'dcf'},
          'label': {'type': 'text', 'label': '가정 이름', 'default': ''},
          'shares': {'type': 'text', 'label': '희석 보통주 수 (주)', 'default': ''},
          'share_basis': {'type': 'text', 'label': '주식 수 산정 근거 (10자 이상)', 'default': ''},
          'assumptions_note': {'type': 'text', 'label': '가정 근거 (10자 이상)', 'default': ''},
          'input_kind': {'type': 'enum', 'label': '입력 성격', 'options': ['user_assumptions', 'illustrative_assumptions'], 'default': 'user_assumptions'},
          'model': {'type': 'json', 'label': ASSUMPTION_TEMPLATE_HINT, 'default': {}}}),
    spec('T04', '증권사 전망 가져오기', 'common', 'tool', 'real',
         '선택한 증권사 보고서 하나에서, 사람이 승인한 전망치만 내보낸다. 실행할 때 PDF 해시를 다시 확인한다. 여러 보고서를 하나로 합치지 않는다.',
         [], [port('forecasts', 'BrokerForecastPackage')],
         {'report': {'type': 'broker_report', 'label': '적용할 보고서 (하나만)', 'default': ''}},
         [{'id': 'broker-reports', 'provider': '증권사 리서치(사용자 보관 PDF)', 'scope': '삼성전자 2026-08~11 기업분석 15건',
           'as_of': '2026-11-06', 'collected_at': '2026-11-06', 'rights_status': 'unchecked_research_only'}]),
    spec('T05', '보고서 취합', 'common', 'tool', 'real',
         '연결된 노드 결과를 관점별 기본/확장으로 정리하고, 확인·보류·미연결을 그대로 나눠 보여 준다. 새 판단을 만들지 않는다.',
         [port('results', 'Any', multiple=True, label='모든 결과')], [port('report', 'Report')]),
    spec('T06', '가격·거래량 자료', 'common', 'tool', 'real',
         'Neon 공용 DB의 금융위원회 일별 시세를 PC에서 고정한 사본(_sources/neon)으로 읽는다. 실행마다 사본 해시를 다시 대조하고, 기준시점에 확정된 거래일까지만 쓴다. 수정주가가 아니다.',
         [], [port('prices', 'PriceSeries')],
         {'company': {'type': 'company', 'label': '기업 (이름·종목코드)', 'scope': 'market', 'default': '005930'},
          'snapshot': {'type': 'text', 'label': '사본 이름 (비우면 최신)', 'default': ''},
          'lookback': {'type': 'enum', 'label': '불러올 거래일 수', 'options': [260, 520, 1300], 'default': 260}},
         [{'id': 'neon-price-daily-fsc', 'provider': '금융위원회 주식시세정보 (Neon 공용 DB 경유)', 'scope': '사본에 담긴 국내 상장기업(현재 210곳) 일별 시가·고가·저가·종가·거래량 (수정주가 아님)', 'as_of': '사본 기준시각', 'collected_at': '사본 manifest 참고', 'rights_status': 'public_official (팀 공용 DB, 표 담당자 동의 확인 필요)'}]),
    spec('T07', '투자자별 수급 자료', 'common', 'tool', 'real',
         'Neon 공용 DB의 투자자별 순매수(네이버 수집, 포털 등급)와 대차잔고(금융위)를 PC에서 고정한 사본으로 읽는다. 실행마다 해시 재대조, 기준시점 확정 거래일까지만. 수량(주) 기준.',
         [], [port('flows', 'FlowSeries')],
         {'company': {'type': 'company', 'label': '기업 (이름·종목코드)', 'scope': 'market', 'default': '005930'},
          'snapshot': {'type': 'text', 'label': '사본 이름 (비우면 최신)', 'default': ''},
          'lookback': {'type': 'enum', 'label': '불러올 거래일 수', 'options': [260, 520, 1000], 'default': 260}},
         [{'id': 'neon-investor-flow', 'provider': '네이버 금융 투자자별 매매 (Neon 공용 DB 경유)', 'scope': '외국인·기관·개인 순매수(주), 외국인 보유율', 'as_of': '사본 기준시각', 'collected_at': '사본 manifest 참고', 'rights_status': 'portal (공식 대조 전)'},
          {'id': 'neon-stock-lending', 'provider': '금융위원회 대차거래 (Neon 공용 DB 경유)', 'scope': '대차 잔고·체결·상환', 'as_of': '사본 기준시각', 'collected_at': '사본 manifest 참고', 'rights_status': 'public_official'}]),
    spec('T08', '뉴스·사건 자료', 'common', 'tool', 'real',
         'DART 공시 목록(공식, 접수일)과 네이버 뉴스 제목·링크·날짜(포털, 본문 없음, 같은 제목 합침), 사전 기반 감성 점수·검색 건수를 PC에서 고정한 사본으로 읽는다. 기준시점에 확정된 날까지만. 공시는 보고서명 규칙으로 분류한다.',
         [], [port('events', 'NewsEvents')],
         {'company': {'type': 'company', 'label': '기업 (이름·종목코드)', 'scope': 'market', 'default': '005930'},
          'snapshot': {'type': 'text', 'label': '사본 이름 (비우면 최신)', 'default': ''},
          'lookback_days': {'type': 'enum', 'label': '살펴볼 기간 (일)', 'options': [90, 180, 365], 'default': 180}},
         [{'id': 'neon-disclosure', 'provider': 'DART 공시 목록 (Neon 공용 DB 경유)', 'scope': '보고서명·접수일·접수번호', 'as_of': '사본 기준시각', 'collected_at': '사본 manifest 참고', 'rights_status': 'public_official'},
          {'id': 'neon-news-title', 'provider': '네이버 뉴스 제목·링크 (Neon 공용 DB 경유)', 'scope': '제목·링크·발행일만 (본문 미사용)', 'as_of': '사본 기준시각', 'collected_at': '사본 manifest 참고', 'rights_status': 'portal (제목·링크만)'}]),
    spec('T09', '산업·비교기업 자료', 'common', 'tool', 'real',
         '팀이 고른 비교기업 묶음(선정 이유 포함)과 비교기업의 분기 재무(DART·SEC)·시가총액(금융위)을 PC에서 고정한 사본으로 읽는다. 업종 자동 묶음은 쓰지 않는다. 분기 말 후 45일이 지난 재무만 쓴다.',
         [], [port('peers', 'IndustryPeers')],
         {'company': {'type': 'enum', 'label': '기업', 'options': list(COMPANIES), 'default': '005930'},
          'snapshot': {'type': 'text', 'label': '사본 이름 (비우면 최신)', 'default': ''}},
         [{'id': 'neon-peer-group', 'provider': '팀 공용 DB 비교기업 묶음 (manual:반도체)', 'scope': '국내·해외 반도체 30곳과 선정 이유', 'as_of': '사본 기준시각', 'collected_at': '사본 manifest 참고', 'rights_status': 'team_registered'},
          {'id': 'neon-peer-fin', 'provider': 'DART·SEC EDGAR 분기 재무 (Neon 공용 DB 경유)', 'scope': '매출·영업이익·순이익·자산·부채·자본', 'as_of': '사본 기준시각', 'collected_at': '사본 manifest 참고', 'rights_status': 'public_official'}]),
    spec('T10', '거시 지표 시계열', 'common', 'tool', 'real',
         'FRED·한국은행 ECOS·관세청의 거시 지표 25종(환율·금리·물가·반도체 수출입 등)을 PC에서 고정한 사본으로 읽는다. 공개 시차(월별 약 45일)를 반영해 기준시점에 공개된 관측만 쓴다.',
         [], [port('macro', 'MacroSeries')],
         {'snapshot': {'type': 'text', 'label': '사본 이름 (비우면 최신)', 'default': ''}},
         [{'id': 'neon-macro', 'provider': 'FRED·한국은행 ECOS·관세청 (Neon 공용 DB 경유)', 'scope': '거시 지표 25종', 'as_of': '사본 기준시각', 'collected_at': '사본 manifest 참고', 'rights_status': 'public_official'}]),
    spec('T11', '회사 공시 재무·민감도', 'common', 'tool', 'real',
         'DART 정기보고서 재무(공시 API, 연결 우선)와 사업보고서 표에서 읽은 환율·금리 민감도를 PC에서 고정한 사본으로 읽는다. 기준시점 이전에 접수된 보고서만. 원문 셀 대조 값은 아니다.',
         [], [port('filings', 'CompanyFilings')],
         {'company': {'type': 'company', 'label': '기업 (이름·종목코드)', 'scope': 'market', 'default': '005930'},
          'snapshot': {'type': 'text', 'label': '사본 이름 (비우면 최신)', 'default': ''}},
         [{'id': 'neon-financial-fact', 'provider': 'DART 공시 API 재무 (Neon 공용 DB 경유)', 'scope': '주요 14개 계정, 연간·분기 보고서', 'as_of': '사본 기준시각', 'collected_at': '사본 manifest 참고', 'rights_status': 'public_official'},
          {'id': 'neon-report-exposure', 'provider': '사업보고서 민감도 표 규칙 추출 (Neon 공용 DB 경유)', 'scope': '환율·금리 민감도, 외화 자산·부채, 수출 비중', 'as_of': '사본 기준시각', 'collected_at': '사본 manifest 참고', 'rights_status': 'public_official (추출 규칙: 팀)'}]),
    spec('T02', '사업보고서 문장 검색', 'common', 'tool', 'real',
         '저장된 사업보고서 원문(DART HTML)을 문단으로 나눈 색인에서 검색어에 맞는 문단을 원문 그대로 가져온다. 문단마다 원문 파일 해시·문단 해시·접수번호를 붙이고, 기준시점 뒤에 접수된 보고서는 뺀다.',
         [], [port('docs', 'DocPassages')],
         {'company': {'type': 'enum', 'label': '기업 (원문 보유: 두 기준 기업)', 'options': list(COMPANIES), 'default': '005930'},
          'preset': {'type': 'enum', 'label': '찾을 내용', 'options': ['competition', 'holders', 'risk'], 'default': 'competition'},
          'query': {'type': 'text', 'label': '직접 검색어 (비우면 위 항목)', 'default': ''},
          'k': {'type': 'enum', 'label': '가져올 문단 수', 'options': [5, 10, 20], 'default': 10}},
         [{'id': 'dart-full-local', 'provider': 'DART 사업보고서 원문 (PC 저장본)', 'scope': '삼성전자·SK하이닉스 2025 사업보고서 전 섹션', 'as_of': '접수일', 'collected_at': '_sources/dart_full', 'rights_status': 'public_official'}]),
    spec('T12', '지분·대주주 공시', 'common', 'tool', 'real',
         '최대주주 및 특수관계인 현황(사업보고서), 대량보유(5%) 보고, 임원·주요주주 소유 보고 개수를 PC에서 고정한 사본으로 읽는다. 기준시점 이전 접수분만.',
         [], [port('ownership', 'OwnershipData')],
         {'company': {'type': 'company', 'label': '기업 (이름·종목코드)', 'scope': 'market', 'default': '005930'},
          'snapshot': {'type': 'text', 'label': '사본 이름 (비우면 최신)', 'default': ''}},
         [{'id': 'neon-holders', 'provider': 'DART 최대주주·대량보유 (Neon 공용 DB 경유)', 'scope': '최대주주·특수관계인 지분, 5% 보고', 'as_of': '사본 기준시각', 'collected_at': '사본 manifest 참고', 'rights_status': 'public_official'}]),
    spec('N01', '실적·현금흐름 분석', 'fundamentals', 'basic', 'real',
         '공식 원문 셀에서 매출·영업이익·CFO 등을 확인하고 기간·단위·연결/별도 범위와 셀 위치를 보존한 사실 패키지를 만든다. 다른 회사는 T11(공시 API 재무)을 이어 같은 형식으로 담는다(원문 셀 대조 아님 표시).',
         [port('corpus', 'OfficialCorpus', required=False, auto=True),
          port('filings', 'CompanyFilings', required=False, multiple=True, label='다른 회사 공시 재무 (T11)')], [port('facts', 'FactPackage')],
         {'companies': {'type': 'multi', 'label': '기업 (원문 셀 대조: 두 기준 기업)', 'options': list(COMPANIES), 'default': list(COMPANIES)},
          'years': {'type': 'multi', 'label': '연도', 'options': [2024, 2025], 'default': [2024, 2025]},
          'metrics': {'type': 'multi', 'label': '항목', 'options': list(FACT_METRICS), 'default': ['revenue', 'operatingProfit', 'cfo', 'assets', 'liabilities']}},
         OFFICIAL_SOURCES[:2], reuse=REUSE_4373),
    spec('N02', '가치평가·실적 전망 시나리오', 'fundamentals', 'extension', 'real',
         'N01 사실을 원문과 다시 대조한 뒤, 사용자 가정(필요하면 승인된 외부 전망)으로 DCF·DDM·RIM·NAV를 계산하고 민감도를 보인다. 목표주가·매매 의견이 아니다.',
         [port('facts', 'FactPackage'), port('assumptions', 'AssumptionSet'),
          port('forecasts', 'BrokerForecastPackage', required=False)],
         [port('valuation', 'ValuationResult')],
         {'company': {'type': 'enum', 'label': '기업', 'options': list(COMPANIES), 'default': '005930'},
          'base_year': {'type': 'enum', 'label': '기준연도', 'options': [2025, 2024], 'default': 2025},
          'apply_forecast': {'type': 'enum', 'label': '승인된 증권사 전망을 DCF 성장률·이익률에 적용', 'options': ['yes', 'no'], 'default': 'yes'}},
         reuse=REUSE_4373),
    spec('N03', '산업 위치·비교기업 현황', 'industry', 'basic', 'real',
         '팀이 고른 반도체 비교군 중 「반도체 제조·설계」 기업과 최근 4분기 매출 성장률·영업이익률·순이익률·ROE·부채비율, 국내 시가총액 순위를 비교한다. 분기 재무로 직접 계산하며 우열·매매 판단이 아니다.',
         [port('peers', 'IndustryPeers')], [port('finding', 'NodeFinding')]),
    spec('N04', '제품·시장 경쟁력 심층 비교', 'industry', 'extension', 'real',
         'T02가 찾은 사업보고서 문단에서 점유율·경쟁사·순위·시장 규모가 들어간 문장을 원문 그대로 발췌하고 숫자 표현을 표시한다. T09를 이으면 비교군을 함께 보인다. 경쟁력 우열·전망을 판단하지 않는다.',
         [port('docs', 'DocPassages'), port('peers', 'IndustryPeers', required=False)], [port('finding', 'NodeFinding')]),
    spec('N05', '기업별 거시 노출 분석', 'macro', 'basic', 'real',
         '2025 한국은행 기준금리·연준 H.10 원/달러 관측과 각 기업이 공시한 환율·금리 노출 문장을 나란히 보인다. 다른 회사는 T11의 공시 민감도 표(규칙 추출)를 쓴다. 인과·실적 기여를 추정하지 않는다.',
         [port('corpus', 'OfficialCorpus', required=False, auto=True),
          port('filings', 'CompanyFilings', required=False, multiple=True, label='다른 회사 공시 재무 (T11)')], [port('exposure', 'MacroExposure')], sources=OFFICIAL_SOURCES[2:], reuse=REUSE_4373),
    spec('N06', '거시 시나리오·민감도', 'macro', 'extension', 'real',
         '기업이 공시한 환율·금리 민감도를 비교하고, T10을 연결하면 사업보고서 기준일 이후 실제 환율·기준금리 변화를 비례로 넣은 「이 가정이라면」 영향을 계산한다. 예측·회귀는 하지 않는다.',
         [port('exposure', 'MacroExposure'), port('macro', 'MacroSeries', required=False)], [port('finding', 'NodeFinding')],
         {'scenario': {'type': 'text', 'label': '내 가정 (예: 환율 3% 상승, 금리 50bp 인하) — 비우면 건너뜀', 'default': ''}}, reuse=REUSE_4373),
    spec('N07', '수급·유동성 현황', 'flow', 'basic', 'real',
         '주체별 기준일·5/20/60일 누적 순매수와 거래량 대비 비중, 연속 순매수 일수, 외국인 보유율 변화, 대차잔고를 계산한다. 포털 수집값임을 표시하며 매매 판단이 아니다.',
         [port('flows', 'FlowSeries'), port('prices', 'PriceSeries', required=False, auto=True, label='가격·거래대금 (T06) — 유동성 계산용')], [port('finding', 'NodeFinding')]),
    spec('N08', '수급 전환·가격 불일치', 'flow', 'extension', 'real',
         '20일 누적 순매수의 방향 전환, 외국인 매매와 주가가 엇갈린 날, 같은 날 상관을 계산한다. 원인 해석·방향 판단은 하지 않는다.',
         [port('flows', 'FlowSeries'), port('prices', 'PriceSeries')], [port('finding', 'NodeFinding')]),
    spec('N09', '가격·추세·거래량 기본', 'technical', 'basic', 'real',
         '기간 수익률·이동평균과의 차이·1년 최고/최저·거래량 비교와 방향이 다른 지표를 계산한다. 과거 요약이며 매매 판단이 아니다.',
         [port('prices', 'PriceSeries')], [port('finding', 'NodeFinding')]),
    spec('N10', '거래량·변동성·추세 심층', 'technical', 'extension', 'real',
         '실현 변동성·최대 낙폭·거래량 급증일·추세 지속 비율과 이동평균 배열 규칙에 따른 국면(상승·하락·전환·횡보)을 계산한다. 국면은 규칙 분류이며 판단이 아니다. 원인 해석은 하지 않는다.',
         [port('prices', 'PriceSeries')], [port('finding', 'NodeFinding')]),
    spec('N11', '주요 사건·감성 현황', 'sentiment', 'basic', 'real',
         '기간 안의 공시를 규칙으로 분류해 세고(반복 공시 따로), 주요 공시 목록, 주별 뉴스 제목 수, 사전 기반 감성 점수의 전·후반 변화, 검색 건수 변화를 보인다. 기대·우려·호재·악재를 판단하지 않는다.',
         [port('events', 'NewsEvents')], [port('finding', 'NodeFinding')]),
    spec('N12', '심리 변화·후속 시장 반응', 'sentiment', 'extension', 'real',
         '주요 공시 뒤 1·5·20거래일 주가 수익률, 코스피 대비 차이(비공식 지수), 거래량 배수를 공시별·분류별로 계산한다. 표본 5건 미만은 경향으로 보지 말라고 표시한다. 원인·일반화 판단은 하지 않는다.',
         [port('events', 'NewsEvents'), port('prices', 'PriceSeries')], [port('finding', 'NodeFinding')],
         {'snapshot': {'type': 'text', 'label': '지수 사본 이름 (비우면 최신)', 'default': ''}}),
    spec('N13', '대주주·경영진 지분', 'fundamentals', 'addon', 'real',
         '최대주주와 특수관계인 지분 합계(연말)와 변화, 대량보유(5%) 보고 내역, 임원·주요주주 소유 보고 건수를 보인다. T02(주주 문단)를 이으면 원문과 이름·지분율을 대조한다. 지배구조 평가는 하지 않는다.',
         [port('ownership', 'OwnershipData'), port('docs', 'DocPassages', required=False)], [port('finding', 'NodeFinding')]),
    spec('N14', '수출 통계로 실적 조기 확인', 'fundamentals', 'addon', 'real',
         '관세청 월간 수출(다음 달 1일 공개)을 분기로 합해 원화로 바꾸고, 직전 4분기 「매출 ÷ 원화 수출」 비율 범위를 곱해 아직 공시 전인 분기 매출 범위를 계산한다. 과거 맞히기 오차 중앙값이 15%를 넘으면 보류한다. 모델 추정이며 예측·원인 분석이 아니다.',
         [port('filings', 'CompanyFilings'), port('macro', 'MacroSeries')], [port('finding', 'NodeFinding')],
         {'export_series': {'type': 'enum', 'label': '수출 품목', 'options': ['KCS_EXP_854232_USD', 'KCS_EXP_854231_USD'], 'default': 'KCS_EXP_854232_USD'}}),
    spec('N15', '관계 기록 조사', 'macro', 'addon', 'real',
         '주가 월간 수익률과 환율·지수·금리·수출 등의 월간 변화가 함께(또는 시차를 두고) 움직인 기록을 잰다. 최소 24개월, 시차를 여러 개 시험한 만큼 넓힌 범위, 앞·뒤 절반 재확인, 앞선 시차는 과거 맞히기 시험을 거친다. 관계의 기록이며 인과가 아니다.',
         [port('prices', 'PriceSeries'), port('macro', 'MacroSeries')], [port('finding', 'NodeFinding')],
         {'factors': {'type': 'multi', 'label': '비교할 지표', 'options': ['ECOS_USDKRW', '^KS11', '^KQ11', '^SOX', '^GSPC', 'ECOS_KTB3Y', 'ECOS_KTB10Y', 'DGS10', 'ECOS_BASE_RATE', 'KCS_EXP_854232_USD', 'KCS_EXP_854231_USD', 'DCOILBRENTEU', 'DEXJPUS', 'DEXCHUS', 'IPG3344S', 'PCOPPUSDM'],
                      'default': ['ECOS_USDKRW', '^KS11', '^SOX', 'ECOS_KTB3Y', 'DGS10', 'KCS_EXP_854232_USD', 'DCOILBRENTEU']},
          'snapshot': {'type': 'text', 'label': '지수 사본 이름 (비우면 최신)', 'default': ''}}),
    spec('T13', '승인된 증권사 전망 원장', 'common', 'tool', 'real',
         '한 회사의 증권사 보고서 중 사람이 승인한 연간 매출·영업이익 전망을 모은다. 기준 날짜 뒤 보고서는 쓰지 않고, PDF 해시를 다시 대조한다. 외부 전망이며 사실이 아니다. 목표주가는 담지 않는다.',
         [], [port('ledger', 'ForecastLedger')],
         {'company': {'type': 'company', 'label': '기업 (이름·종목코드)', 'scope': 'market', 'default': '005930'}}),
    spec('N16', '증권사 전망 추이·집계', 'fundamentals', 'addon', 'real',
         '날짜마다 증권사별 최신 전망(120일 넘은 것 제외)의 중앙값·범위·보고서 수와 상향·하향 수를 계산한다. 공시가 나오면 공시 전날까지의 집계와 실제를 비교해 기록한다. 컨센서스가 아니며, 3건 미만이면 추이로 보지 말라고 표시한다.',
         [port('ledger', 'ForecastLedger'), port('filings', 'CompanyFilings', required=False, auto=True)], [port('finding', 'NodeFinding')]),
    spec('N17', '주가가 실적보다 앞선 햇수(EDI)', 'fundamentals', 'addon', 'real',
         '주가를 실적이 받치는 가치(V, 잔여이익 식)와 견줘 「미래 성장 몇 년치를 미리 반영했나」를 햇수로 계산한다. 날짜마다 그때 공개된 분기 재무만 쓰고, V는 정규화 ROE·최근 4분기 ROE·장부가 세 가지를 나란히 보인다. 증권사 전망 원장을 이으면 「그 실적 전망이 맞다면」을 같은 식으로 계산한다. 가정 아래 계산값이며 적정주가·목표주가가 아니다. (KIRI 시간자본론 지표)',
         [port('prices', 'PriceSeries'), port('filings', 'CompanyFilings'), port('ledger', 'ForecastLedger', required=False, auto=True)], [port('finding', 'NodeFinding')],
         {'cost_of_equity': {'type': 'text', 'label': '자기자본비용 r (%)', 'default': '9'},
          'long_growth': {'type': 'text', 'label': '장기성장률 (%)', 'default': '2'},
          'edi_growth': {'type': 'text', 'label': 'EDI 기준 연 성장률 g (%)', 'default': '8'},
          'extra_shares': {'type': 'text', 'label': '보통주 외 주식 수 (우선주 등, 비우면 0)', 'default': ''}}),
    spec('N18', '실적·가격 격차 국면 기록', 'fundamentals', 'addon', 'real',
         '실적이 반영된 날부터 다음 실적이 반영된 날까지를 한 구간으로, 주가와 실적이 받치는 가치(V)의 격차가 어느 쪽 때문에 벌어지거나 줄었는지 기록한다. EDI 변화 1년 미만은 「변화 작음」, 줄어든 몫의 70% 이상이 한쪽이면 그쪽 「주도」, 재무가 오래됐거나 가정에 따라 결론이 갈리면 그대로 표시한다. 지난 기록이며 방향·매매 판단이 아니다. (KIRI 시간자본론 지표)',
         [port('prices', 'PriceSeries'), port('filings', 'CompanyFilings')], [port('finding', 'NodeFinding')],
         {'cost_of_equity': {'type': 'text', 'label': '자기자본비용 r (%)', 'default': '9'},
          'long_growth': {'type': 'text', 'label': '장기성장률 (%)', 'default': '2'},
          'edi_growth': {'type': 'text', 'label': 'EDI 기준 연 성장률 g (%)', 'default': '8'}}),
    spec('T14', '사업부별 매출 자료', 'common', 'tool', 'real',
         '정기보고서(사업·반기·분기) 연결재무제표 주석의 「부문별 보고」 표를 DART 원문 사본에서 읽는다. 원문 해시를 다시 대조하고 기준 날짜 뒤 보고서는 쓰지 않는다. '
         '자격 관문(설명 안 되는 합계 불일치 0건 + 분기 연결 합계가 분기 재무와 일치)을 통과한 회사만 값을 넘기고, 아니면 사유를 넘긴다.',
         [], [port('segments', 'SegmentRevenue')],
         {'company': {'type': 'company', 'label': '기업 (이름·종목코드)', 'scope': 'market', 'default': '005930'}}),
    spec('N19', '사업부별 분기 매출', 'industry', 'addon', 'real',
         '사업부·제품·지역별 단독분기 매출(원문 3개월 값 우선, 없으면 누적 차감)과 전년 동기 대비를 보인다. 같은 정의끼리만 비교하고, 자격 관문을 통과하지 못한 회사는 사유만 보인다. 사업의 좋고 나쁨을 판단하지 않는다.',
         [port('segments', 'SegmentRevenue')], [port('finding', 'NodeFinding')]),
    spec('T15', '공시 원문 1건', 'common', 'tool', 'real',
         '접수번호 하나의 DART 공시 원문을 사본에서 해시를 다시 대조해 읽는다(주식 소각 결정 · 자기주식 취득 결정 · 현금·현물 배당 결정 · 영업(잠정)실적). '
         '자회사 공시와 기준 날짜 뒤의 공시는 쓰지 않는다. 배당은 같은 회사의 앞선 배당 결정도 함께 읽는다. 원문 칸 값 그대로이며 읽지 못한 칸은 비워 둔다.',
         [], [port('filing', 'FilingDoc')],
         {'company': {'type': 'company', 'label': '기업 (이름·종목코드)', 'scope': 'market', 'default': '005930'},
          'rcept_no': {'type': 'text', 'label': 'DART 접수번호 (14자리)', 'default': ''}}),
    spec('N20', '공시 1건 숫자로 보기', 'fundamentals', 'addon', 'real',
         '공시 원문의 칸 값과, 그 값을 공시 전 마지막 거래일 시가총액·상장 주식 수·거래대금이나 앞선 같은 종류 공시와 나눈 비율을 보인다. '
         '무엇을 무엇으로 나눴는지 식을 함께 적는다. 호재·악재 같은 방향 판단은 하지 않는다. (v0.38 공시 1등급)',
         [port('filing', 'FilingDoc'), port('prices', 'PriceSeries', required=False, auto=True)], [port('finding', 'NodeFinding')]),
]
SPECS = {s['id']: s for s in REGISTRY}
SPECIALISTS = [s for s in REGISTRY if s['tier'] in ('basic', 'extension')]

# Which tool feeds which specialist input type in generated plans.
TYPE_SOURCE = {'OfficialCorpus': 'T01', 'AssumptionSet': 'T03', 'BrokerForecastPackage': 'T04',
               'PriceSeries': 'T06', 'FlowSeries': 'T07', 'NewsEvents': 'T08', 'IndustryPeers': 'T09', 'MacroSeries': 'T10', 'CompanyFilings': 'T11', 'DocPassages': 'T02', 'OwnershipData': 'T12', 'ForecastLedger': 'T13', 'SegmentRevenue': 'T14', 'FilingDoc': 'T15'}


def plan(perspectives):
    """Agreement rule: basic 6 always, plus the extension of each selected perspective."""
    sel = [p for p in PERSPECTIVE_IDS if p in set(perspectives)]
    if len(sel) != len(set(perspectives)):
        raise ValueError('unknown_or_duplicate_perspective')
    chosen = [s['id'] for s in SPECIALISTS if s['tier'] == 'basic' or s['perspective'] in sel]
    return {'perspectives': sel, 'specialists': chosen, 'count': len(chosen)}


PLAN_OPTIONAL = {('N06', 'macro'), ('N04', 'peers')}   # v0.28.2: 계획 배치 때 함께 잇는 선택 입력 (빈 「일부 확인」 방지)


def plan_workflow(perspectives, name=None):
    """Build a canvas workflow for a plan. Data tools are added once and wired by type."""
    p = plan(perspectives)
    nodes, edges = [], []
    col_x = {'tool': 40, 'basic': 380, 'extension': 720}
    rows = {}
    used_tools = []

    def add(type_, tier, x=None):
        nid = type_.lower()
        if any(n['id'] == nid for n in nodes):
            return nid
        r = rows.get(tier, 0)
        rows[tier] = r + 1
        nodes.append({'id': nid, 'type': type_, 'x': x if x is not None else col_x[tier], 'y': 40 + r * 130, 'config': with_defaults(type_, {})})
        return nid

    for sid in p['specialists']:
        add(sid, SPECS[sid]['tier'])
    for sid in p['specialists']:
        for inp in SPECS[sid]['inputs']:
            if not inp['required'] and not inp.get('auto') and (sid, inp['name']) not in PLAN_OPTIONAL:
                continue  # optional ports (e.g. N02 forecasts) are wired by the user on purpose
            src = None
            if inp['type'] == 'FactPackage':
                src, sport = 'n01', 'facts'
            elif inp['type'] == 'MacroExposure':
                src, sport = 'n05', 'exposure'
            elif inp['type'] in TYPE_SOURCE:
                tool = TYPE_SOURCE[inp['type']]
                if tool not in used_tools:
                    used_tools.append(tool)
                src = add(tool, 'tool')
                sport = SPECS[tool]['outputs'][0]['name']
            if src:
                edges.append({'from_node': src, 'from_port': sport, 'to_node': sid.lower(), 'to_port': inp['name']})
    rep = add('T05', 'extension', x=1060)
    for sid in p['specialists']:
        edges.append({'from_node': sid.lower(), 'from_port': SPECS[sid]['outputs'][0]['name'], 'to_node': rep, 'to_port': 'results'})
    return {'name': name or f"조사 계획 ({p['count']}개 전문노드)", 'nodes': nodes, 'edges': edges, 'plan': p}


def with_defaults(type_, cfg):
    """Fill missing config keys from the spec defaults (single source of truth)."""
    out = {k: (v.get('default') if not isinstance(v.get('default'), (list, dict)) else type(v['default'])(v['default']))
           for k, v in SPECS[type_]['config_schema'].items()}
    out.update(cfg or {})
    return out
