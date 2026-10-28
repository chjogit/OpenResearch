# 두 Agent 기본 구현 주피터 패키지

## 빠른 시작

Python 3.12 이상 환경에서 ZIP을 압축 해제하고 OpenResearch_BasicAgents 폴더로 이동합니다.

    python -m pip install -r requirements-basic-agents.txt
    python -m jupyterlab

notebooks/두_Agent_기본구현_Python_LLM.ipynb를 열어 위에서부터 실행합니다.
기본 실행에는 API 키, Neon DB, 웹 서버가 필요하지 않습니다.

## 포함 기능

- 산업·사업모델: 검수된 주장·근거 연결, 원문에 명시된 전년/현재 비율의 차이 계산.
  경쟁 강도 5개 항목은 자료 미확보로 표시하고 후속 조사 요청을 제공합니다.
- 기술적 분석: 종가·거래량 검사, 이동평균·직전 관측 수익률·거래량 변화·비연율화 변동성.
- 설명: 오프라인 데모 문구와 실제 LLM 미검증 해설을 구분합니다.
- ML/DL: model_tool.predict의 반환 계약과 미학습 Hook을 제공합니다. 학습 코드·학습 가중치는 없습니다.
- 결과 비교: 같은 reportId·contentRevision·inputDigest인지 검사합니다. 최종 사실 검증기는 아닙니다.

## 실제 Solar 사용

    python -m pip install -r requirements-basic-agents-solar.txt

.env.example을 .env로 복사해 UPSTAGE_API_KEY, SOLAR_MODEL을 설정합니다.
실제 사용 가능한 모델 ID를 입력하고 커널을 다시 시작합니다. 노트북의 RUN_LIVE_LLM=True로
바꾸면 두 Agent의 입력 자료가 Upstage로 전송되고 API 비용이 발생할 수 있습니다.
키는 셀·출력·공유 파일에 넣지 마세요. 실제 API는 제작 중 호출하지 않았습니다.
SolarLLM은 기존 agent/llm.py의 get_llm을 사용하며 다른 제공자는 explain(system,payload)로 교체할 수 있습니다.

## 파일 구조

sh_agents/basic_agents.py: 두 Agent·LLM 어댑터·설정·ML/DL 도구 Protocol
sh_agents/research_contract.py: 입력 보고서 참조·버전·digest 검사
examples/data/: 합성 원문·가격·보고서 v1/v2
notebooks/: 실행 노트북

## 연결·버전 경계

출력은 파생 Agent 결과 봉투이며 입력 보고서를 덮어쓰지 않습니다. inputDigest는 입력의 참조값이고
새 결과의 검증 완료나 서명이 아닙니다. 재실행 결과를 공식 보고서에 저장할 때는 별도 결과 ID·계산
설정·모델 버전·새 내용 버전과 Verifier를 연결해야 합니다.
기술적 결과의 TECH_ ID는 기본 실행 내부 ID이므로 영구 저장 시 고유 결과 ID 범위를 추가하세요.
산업 Agent는 입력에 있는 검수된 주장 재사용이 기본이며, 자유 원문에서 새로운 주장을 자동 추출하는
산업 리서치 전체 구현은 아닙니다. 경쟁사 조회·문서 검색은 추후 공용 도구로 연결하세요.

실제 시세는 report/evidence 계약, ISO 날짜의 정렬·기준시점, price_metadata의 adjustment와
sourceDescription을 요구합니다. 공식 거래일 달력·기업행위·자료 공개시각·조정의 진위는 별도 검사입니다.
입력 전체 OHLC 검사는 후속이며 기본 기술 계산은 종가와 거래량만 사용합니다.

## 학습 확장 위치

산업: model_tool에 문단 분류기(TF-IDF/로지스틱 → 사전학습 언어모델) 연결.
기술: 동일 인터페이스에 변동성 회귀/LSTM 연결. 미학습 예시를 예측으로 표시하지 마세요.
모델은 modelVersion·trainingCutoff·status·output·limitations를 반환합니다.
정답·평가셋·누수 검사·기준선 대비 개선을 확인하고 사용하며, 학습 출력은 관측 사실과 구분합니다.

설명 수준과 성향은 사용자가 선택한 표현 설정입니다. 설문 분류나 협업 권한을 대신하지 않습니다.
공통 수치·근거·반대 자료·보류를 프롬프트로 유지하되 실제 LLM 준수 여부는 별도 검증해야 합니다.

## 검사 기록

노트북 코드 셀 8개를 API 없이 실행했습니다. 전체 저장소 테스트 85개 및 공용 코드 린트 통과.
실제 Solar·Neon·실제 시장 데이터·모델 학습 성능은 검증하지 않았습니다.
