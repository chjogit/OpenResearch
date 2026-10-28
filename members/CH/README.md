# CH 작업 폴더

CH 의 개인 작업 공간입니다. 실험 노트북, 스크립트, 메모를 자유롭게 두세요.

- 팀이 함께 쓸 코드가 되면 `agent/` 로 옮겨 PR 로 올립니다.
- `.env`, API 키, DB 접속 주소는 여기에도 커밋하지 않습니다.

## 파일

번호는 교재 8~9장·기초기획서 R4 기준입니다: 에이전트 1 거시경제, 에이전트 3 투자심리·수급 (이전 A1/A4 표기는 쓰지 않음).

| 파일 | 내용 |
| --- | --- |
| `docs/P01_거시경제_상세개발기획서.md` | **에이전트 1 제작 기준** (10-28). 기준과 맞지 않는 기존 출력은 지우지 않고 참고용(`tier=reference`)으로 낮춤 |
| `docs/P03_투자심리수급_상세개발기획서.md` | **에이전트 3 제작 기준** (P01 구조 준용, 10-28) |
| `ch_agents/p01.py` | P01 연결: 등급·결과 종류, 과업 계약(P01Plan)·상태 코드, 분기 자료 점검, 세 줄 요약 |
| `ch_agents/vintage.py`, `forecast.py`, `scenario.py`, `anomaly.py` | P01 기능: 공표 시점 규칙(F02), 다음 분기 매출 기준선 B0/B1·80% 구간·순차평가(F05), 공시 민감도 시나리오 정적 환산(F07), 거시 이상 점검(F08) |
| `ch_agents/p03.py` | P03 연결: 공개 시점 규칙(대차·검색), 등급, 과업 계약(의도 질문 보류), 사건 연구(종목·KOSPI 200 합산) |
| `ch_agents/etf.py` | 지수·배당 ETF: 에이전트 1 참고용 시장 기준선, 에이전트 3 설정·환매 추정 자금 흐름 |
| `scripts/smoke_p01_p03.py` | 실데이터 점검 (LLM 없이): `python scripts\smoke_p01_p03.py 005930 000660` |
| `ch_agents/agent1_macro.py` | 에이전트 1 거시경제 계산 (`exposure.py`: 노출 점검표·미확인 전제) |
| `ch_agents/agent3_sentiment_flow.py` | 에이전트 3 투자심리·수급 계산 (기준선 비교·중복 신호) |
| `ch_agents/contract.py`, `ch_agents/schema/agent_output.schema.json` | 데이터 계약 (reportId·claimId·evidenceId). 설명은 `docs/DATA_CONTRACT.md` |
| `ch_agents/profile.py`, `ch_agents/renderer.py` | 사용자 프로필(숙련도 L1~L3 × 성향 방어/공격)과 페르소나 렌더러. 설명은 `docs/DATA_CONTRACT.md` 7장 |
| `ch_agents/availability.py`, `docs/DATA_NEEDS_A.md` | 미확인 항목의 채울 방법 분류(수집 중·공시 일부·공시 없음)와, 그 항목을 채우는 데 필요한 데이터 목록 |
| `ch_agents/` 나머지 | 장부(`facts.py`), LLM 계층(`llm.py`), Verifier 연동(`verify.py`), RAG(`rag.py`), 첨삭(`review.py`). `financial.py`는 이관 참고용(7번) |
| `ch_agents_agent1_agent3.ipynb` | 실행·확인 노트북 (데이터 확인 → 교차 검증 → 에이전트 실행 → 데이터 계약 → 첨삭 → 일괄 점검) |
| `tests/` | 패키지 테스트. DB·LLM 없이 실행 |
| `solar_pro_4.ipynb` | 6+1 전체 파이프라인 원본. 참고용이며 더 이상 수정하지 않음 |

## 실행 (Windows cmd)

```
cd OpenResearch
pip install -r requirements-dev.txt
python -m pytest members\CH\tests -q
```

노트북은 `members\CH` 폴더에서 열고, `.env`에 `DATABASE_URL`, `UPSTAGE_API_KEY`를 둡니다.

```python
from ch_agents import run_agent
r1 = run_agent(1, "005930", focus=["환율", "금리"])   # 에이전트 1, 관심 거시 변수
r3 = run_agent(3, "005930", period=10, mode="guide")  # 에이전트 3, 관찰 기간(거래일 5~120)
# 제작 기준 과업 계약: 질문·시나리오를 주면 과업별로 답함/보류를 나눔 (계약의 p01·p03)
r1s = run_agent(1, "005930", scenario="환율 5% 상승, 금리 0.5%p 하락", question="그러면 다음 분기 매출은?")
r3q = run_agent(3, "005930", question="외국인이 알고 사는 거야?")   # 의도 부분은 INTENT_NOT_INFERABLE 로 보류
r1["contract"]                                         # 데이터 계약 JSON
```

## 출력 (오케스트레이터 전달용)

`run_agent()`가 돌려주는 dict 키입니다. 팀 공통으로는 `contract`(데이터 계약 JSON)만 보면 됩니다.

| 키 | 내용 |
| --- | --- |
| `contract`, `report_id` | 데이터 계약 JSON (`docs/DATA_CONTRACT.md`)과 그 reportId |
| `agent_id`, `agent_name`, `status` | 상태: 완료 / 완료 (수정 1회) / 완료 (일부 문장 제외) / 규칙 기반 대체 |
| `period`, `as_of` | 관측 기간과 기준일 |
| `result` | 핵심진단, 주장·반대근거(claimId·문장·구분·근거 키·출처), 긍정요인, 리스크요인, 미확인, 다음점검, 자체점수 |
| `facts`, `gaps`, `flags` | 숫자 장부, 무자료 목록, 코드 판정 |
| `checks`, `removed`, `attempts` | 코드 검사 결과, 최종 출력에서 뺀 문장, LLM 시도 기록 |
| `claim_stats` | 품질 지표: 남은 주장·반대근거 수, claimId 가 있는 Verifier 통과 수, 전체 대조 수, 뺀 문장 수, 개수 상한(주장 7·반대근거 3)으로 자른 수 |
| `analysis`, `source` | 사람이 읽는 마크다운(키를 값으로 바꾼 것), 출처 |
| `docs` | RAG로 고른 참고 문서 목록 (`D1`부터 순서대로). 공시는 `kind="공시"` |
| `verification` | Verifier 대조 기록: claimId, 문장, ok, unmatched, sources(출처 태그), evidenceIds |
| `exposure`, `premises` | 에이전트 1 노출 점검표 행, 미확인 전제 목록 |
| `contract["p01"]`, `contract["p03"]` | 제작 기준 과업 계약: 과업 상태·상태 코드·보류 사유·세 줄 요약 (P03 은 사건 연구 표 포함). 근거마다 `tier`·`resultType` |
| `anomalies`, `baseline`, `dup_clusters` | 에이전트 3 이상 징후, 기준선 비교 행, 중복 신호 묶음 |
| `quality` | 데이터 품질 주의 원천 (quality.api_status 기준) |

`result`의 문장은 숫자 대신 `{M1}` 같은 키를 담고 있습니다. `contract`에서는 값을 채운 문장(`text`)과 근거 ID(`E01`…)로 바뀝니다.

사용자에게 보여 줄 때는 계약을 프로필별로 렌더링합니다. LLM 을 다시 부르지 않고, 수치·근거·판정은 프로필과 무관합니다.

```python
from ch_agents import render, render_all
view = render(out["contract"], {"level": "L1", "stance": "defensive"})   # view["markdown"], view["sections"]
views = render_all(out["contract"])                                       # 6개 프로필 모두
```

## DB 기반 RAG (`ch_agents/rag.py`)

교재 번호로 프리셋이 있습니다. 에이전트 1·3은 자동으로 붙고, 팀원은 아래처럼 바로 씁니다.

```python
from ch_agents.rag import retrieve, docs_for_prompt
docs = retrieve(5, "005930", as_of="2026-10-26")   # 관점 번호 1·2·3·4·5·7
prompt_block = docs_for_prompt(docs)                # 프롬프트에 붙일 D1, D2 ... 목록
```

| 관점 | 문서 | 공시 유형 |
| --- | --- | --- |
| 1 거시경제 | 뉴스 30일 (환율·금리·관세·수출·물가·유가) + 사업보고서 환위험 문단 500일 | 없음 |
| 2 산업·사업모델 | 뉴스 60일 (점유율·수주·증설·판가·규제) | 공급계약·시설투자·지분취득·합병 등 1년 |
| 3 투자심리·수급 | 뉴스+블로그·카페·댓글 20일 (외국인·기관·공매도·심리) | 풍문 해명·조회공시·전환권 행사 120일 |
| 4 기술적 분석 | 뉴스+블로그·카페·댓글 20일 (신고가·이평선·거래량) | 없음 |
| 5 경영진·대주주 | 뉴스 60일 (최대주주·경영권·지배구조·승계·행동주의) | 최대주주 지분 변동·지배구조·주총·소송 등 1년 |
| 7 재무(가치평가·위험 참고) | 뉴스 45일 (실적·배당·자사주·부채·신용등급) | 잠정실적·감사보고서·배당·자기주식·유상증자 등 1년 |

- 검색: SQL로 종목·기간·출처를 좁혀 용어 일치 후보를 뽑고, 파이썬이 점수(용어 가중치 × 제목/요약 × 출처 × 최신성)를 매깁니다.
- 거르기: 종목명이 없는 문서, 사진 기사, 비슷한 제목, 출처별 개수 초과.
- 규칙: 문서 속 숫자는 쓰지 않습니다(코드 검사가 지움). 개인 의견 문서만으로는 '사실' 주장을 못 합니다.
- 한계: 공시는 제목만 있습니다(본문 없음). 벡터 검색은 `rag.chunk`가 비어 있어 아직 쓰지 않습니다.

## 기초기획서 R4 대응 (에이전트 1·3)

| 기획서 요구 | 구현 |
| --- | --- |
| 번호 체계 통일 | `AGENTS`·`MY_AGENTS=(1, 3)`·RAG 프리셋·프롬프트 절(`## 에이전트 1`)·모듈명(`agent1_macro`, `agent3_sentiment_flow`) |
| 데이터 계약 | `contract.py` + JSON 스키마: reportId, claimId, evidenceId, 사실·해석·예측, 반대 근거(`role=counter`)·하방 위험, 미확인 상태, 자료 기준일·공개시각, 출처 태그 |
| 에이전트 1 입력: 관심 거시 변수 | `run_agent(1, ticker, focus=["환율", "금리"])` |
| 에이전트 1 노출도 (규칙 기반 우선) | `exposure.py`: ① 회사 공시값(사업보고서 원문 표) → 없으면 업종 기본값 ② 주가 동조성(유의·\|상관\|≥0.3이면 상향) ③ 부채비율(금리) |
| 에이전트 1 미확인 전제 | `exposure.premises()`: 환헤지 여부·비율, 결제 통화·시점, 판가 전가력, 달러 비용 비중, 수출 비중, 차입 조건을 확인/일부 확인/미확인으로 표시. 근거: 원문 노출(`core.report_exposure`, 이자율 민감도 포함), 차입 조건·매출채권 회수기간(`exposure.TERMS_SQL`: `core.debt_balance`·`debt_issue`·`v_dso`). 판가 전가력은 가격변동 원문 발췌 건수만 적고 판단 보류. LLM은 미확인 전제를 가정하지 못함 |
| 에이전트 3 입력: 기간 | `run_agent(3, ticker, period=10)` (거래일, 5~120) |
| 에이전트 3 이상 징후 | 외국인·기관 5일 강도 \|z\|≥2, 거래대금 5일÷60일 ≥2배, 감성 변화 ≥0.15, 검색 관심 2배↑, 대차잔고 20일 +20%↑ |
| 에이전트 3 기준선 비교 | 신호마다 규칙 기준선(직전 60·90일, 8~30일)과 현재 값을 나란히. 감성은 '키워드 감성 사전 기준선(학습 모델 아님, 성능 미검증)' 명시 |
| 에이전트 3 중복 신호 | 최근 창에 뉴스 논조·검색·거래대금·집중 매매 이상 징후가 둘 이상이면 사건 묶음 X1. 이를 독립 근거로 세는 문장은 코드 검사가 지움 |
| 에이전트 3 의도 추정 금지 | '매수 의도·세력·내부 정보' 표현은 코드 검사가 지움 ('추정할 수 없다' 같은 단서 문장은 허용) |
| Verifier | `verify.py`: 수치 1:1 대조 + 출처 태그 + claimId/evidenceId를 대조 기록에 남김 (주장·반대 근거 모두) |
| 프롬프트 expert.md / guide.md 분기 | `ch_agents/prompts/expert.md`, `guide.md` (공통 + 에이전트 1 + 에이전트 3 절) |
| 품질 플래그 참고 | `quality.py`: quality.api_status 연속 실패·48시간 무성공·한도 도달이면 '데이터 품질 주의' |

한계: 회사 공시값은 kic-agent-data `report-exposure`가 사업보고서 원문 표를 찾은 회사만, 차입 조건은 `debt-terms`가 받은 회사만 있습니다. 회사채 발행금리는 발행회사 이름이 종목명과 맞는 건만 씁니다(현대차처럼 공시 이름이 다르면 빠짐). 정기보고서 값은 기말 뒤 제출 기한(사업 90일, 분·반기 45일)이 지난 것만 씁니다. 헤지 효과는 수치로 반영하지 않습니다. 거시 지표의 공표 시각은 수집하지 않아 `publishedAt`이 비어 있습니다(문서·공시만 있음).
