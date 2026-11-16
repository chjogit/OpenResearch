"""Retrieval evaluation cases.

Copied verbatim from 2차_실제/modu-research-agent-tableaware/scripts/table_cases.py
(developer-written draft; not an independent user/expert evaluation). Company: 삼성전자.
Metric here is retrieval-level: are all expected value strings present in the top-k chunks.
That app reported answer-level results (dev 8/8, holdout answerable 8/8) on its PDF index.
"""
DEV = [
    {'id': 'D01', 'question': '직원 수와 평균 근속연수는 어떻게 되나요?', 'values': ['128,881', '13.7']},
    {'id': 'D02', 'question': '연구개발비와 매출액 대비 연구개발비 비율을 알려주세요.', 'values': ['37,754,815', '11.3']},
    {'id': 'D03', 'question': '2025년 연결 매출액과 영업이익을 알려주세요.', 'values': ['333,605,938', '43,601,051']},
    {'id': 'D04', 'question': '2024년과 2025년 별도 매출액을 각각 알려주세요.', 'values': ['209,052,241', '238,043,009']},
    {'id': 'D05', 'question': '연결 기준으로 USD 환율이 5% 상승할 때 당기손익 영향은 2024년과 2025년에 각각 얼마인가요?', 'values': ['365,273', '435,059']},
    {'id': 'D06', 'question': '2025년 DS 부문의 남성과 여성 직원 수 합계를 각각 알려주세요.', 'values': ['56,154', '21,910']},
    {'id': 'D07', 'question': '외부감사인과 감사의견만 알려주세요.', 'values': ['삼정', '적정']},
    {'id': 'D08', 'question': '매출액 자체는 빼고 연구개발비의 매출액 대비 비율만 알려주세요.', 'values': ['11.3']},
]
HOLDOUT = [
    {'id': 'H01', 'question': '기간제까지 포함한 본사 직원 전체 인원과 평균적으로 일한 기간이 궁금합니다.', 'values': ['128,881', '13.7']},
    {'id': 'H02', 'question': '연결 손익표에서 2023년 매출액을 찾아주세요.', 'values': ['258,935,494']},
    {'id': 'H03', 'question': '2025년 연결 기본주당이익은 얼마이며 단위는 무엇인가요?', 'values': ['6,605']},
    {'id': 'H04', 'question': '2025년 여성 직원의 육아휴직 사용자 수를 알려주세요.', 'values': ['3,413']},
    {'id': 'H05', 'question': '2025년 보통주와 우선주의 주당 현금배당금은 각각 얼마인가요?', 'values': ['1,668', '1,669']},
    {'id': 'H06', 'question': '2025년 국내 에너지 사용량을 TJ 단위로 알려주세요.', 'values': ['275,490']},
    {'id': 'H07', 'question': '연구개발비가 매출에서 차지하는 비중만 알려주세요. 매출 금액은 필요 없습니다.', 'values': ['11.3']},
    {'id': 'H08', 'question': '감사를 맡은 회계법인 이름과 적정의견 여부를 확인해 주세요.', 'values': ['삼정', '적정']},
]
