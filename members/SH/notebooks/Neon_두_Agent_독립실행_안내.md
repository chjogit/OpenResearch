# 두 Agent · Neon 독립 실행 패키지

## 파일 선택
- notebooks/01_산업사업모델_Agent_Neon.ipynb : 산업·사업모델 전용
- notebooks/02_기술적분석_Agent_Neon.ipynb : 기술적 분석 전용
어느 노트북이든 독립적으로 실행합니다. 공통 agent 폴더를 함께 보관하세요.
기존 예시 노트북은 그대로 유지했습니다.

## 처음 실행
1. ZIP 전체를 해제합니다.
2. 터미널에서 해제한 폴더로 이동하고 다음 명령을 실행합니다.
   python -m pip install -r requirements-neon-agents.txt
   python -m jupyter lab
3. .env.example를 복사하여 루트에 .env 파일을 만듭니다.
   DATABASE_URL=postgresql://읽기계정:비밀번호@호스트/DB이름?sslmode=require
   UPSTAGE_API_KEY=선택사항
   SOLAR_MODEL=solar-pro
   실제 Neon 콘솔의 연결 문자열을 사용하세요. URL이나 키를 출력·공유하지 마세요.
   agent_reader는 예시 역할명입니다. DB 담당자가 준 읽기 전용 계정 이름을
   EXPECTED_ROLE에 정확히 입력합니다. 관리자 계정으로 변경해서 우회하지 마세요.
4. notebooks에서 원하는 Agent 파일을 열고 위에서 아래로 실행합니다.
5. INPUT_MODE='neon', TICKERS, START/END를 설정합니다. 날짜는 조회 범위이고,
   REFERENCE_DATE는 최신성을 판단할 날짜입니다. 기본값은 한국시간 오늘입니다.
6. 기술적 분석은 PRICE_METADATA_BY_SOURCE에 실제 source 값별 조정 기준과 확인 출처를
   설정해야 합니다. 소스 이름만 보고 unadjusted로 추정하지 않습니다.
7. 먼저 Python 결과를 확인한 뒤, 필요하면 Solar 의존성을 설치하고 RUN_SOLAR=True로 실행합니다.

## 조회와 분석 범위
산업: core.financial_quarter의 요청 기간 재무자료를 별도 표로 보여주고,
rag.document + rag.chunk에 저장된 공시/IR 본문 발췌를 주장·근거·버전으로 연결합니다.
허용 source 이름은 dart, sec_edgar, opendart, sec, ir입니다. 실제 DB 값이 다르면
sh_agents/neon_agents.py의 목록을 담당자와 확인한 후 변경하세요.
뉴스 제목·요약이나 공시 목록만 있으면 원문을 확보한 것으로 간주하지 않습니다.
본문이 없으면 산업 분석은 보류됩니다. 사업보고서의 사업의 내용·매출 구분·경쟁 자료를
원문 위치·URL·공개일과 함께 적재해야 합니다. 이 패키지는 수집/적재를 수행하지 않습니다.

산업 Agent는 기본 근거 정리 및 선택적 LLM 설명 단계입니다. 경쟁 강도 점수, 자동 사업지도,
검증된 종합 결론은 구현하지 않았습니다. 다섯 경쟁 관점은 추가 자료 요청으로 남습니다.
재무 표는 참고 원자료이며, 단위/연결·별도/수정공시를 검증해 해석하는 기능은 후속 개발입니다.

기술적: core.price_daily의 종가·거래량으로 이동평균, 직전 대비 수익률,
관측 수익률의 비연율화 모집단 표준편차, 이전 구간 대비 거래량 변화를 계산합니다.
window=20은 20개 관측이며 20달력일이 아닙니다. OHLC 논리검사와
±30% 가격제한폭 검사는 구현했습니다. 거래일 달력·기업행위는 CSV를 제공할 때만 대조합니다.
미래 예측은 후속 개발입니다.

## 품질 상태별 조치
- 실행 가능: 현재 검사 범위를 통과. 사실 검증·투자 판단 승인과 다릅니다.
- 일부 가능: 제한된 분석을 읽고 원문 지지 여부·공식 달력·누락 관점을 보완합니다.
  현재 실제 데이터는 이런 미검증 항목 때문에 보통 일부 가능으로 표시됩니다.
- 보류: 이 Agent의 계산과 LLM/ML/DL 호출을 차단합니다.
  기간 부족은 실제 데이터를 추가 적재하거나 분석에 적절한 범위를 선택합니다.
  결측·중복은 DB 담당자에게 수정 요청합니다. 결측을 0으로 채우지 않습니다.
  최신성 부족은 수집 작업과 실제 거래일을 확인합니다.
  source 기준 부족은 공급자의 가격 조정 기준 문서로 확인합니다.
  schema_or_permission/unavailable은 표·컬럼·권한·날짜 형식·접속 상태를 확인합니다.
  truncated는 조회 상한을 초과했다는 뜻입니다. 기간/대상을 줄이거나 수집 범위를 재설계합니다.
  기본 상한은 표당 2,000행, 산업 문서는 기업당 3건·문서당 2,000조각(100개씩 조회)입니다. 몰래 일부만 분석하지 않습니다.

## 버전과 보안
동일 읽기 전용 트랜잭션에서 조회합니다. 각 문서 발췌 해시는 DB에 보관된 텍스트의 해시이며
원본 파일 해시가 아닙니다. report.digest는 입력 스냅샷을 식별합니다.
같은 공통 스냅샷 파일을 읽은 두 노트북은 같은 digest를 갖습니다. 서로 다른 digest의 결과를 동일 버전으로 합치지 마세요.
자동 재조회 버전 이력, 원본 공시 변경 추적, 과거 시점 백테스트는 구현하지 않았습니다.
과거 재무 데이터의 당시 공개 여부를 확보했다고 간주해서는 안 됩니다.
.env/원문/결과를 공개 GitHub에 올리지 마세요. SAVE_RESULTS는 기본 False입니다.
Solar는 선택 실행이며 외부 서비스에 입력 근거를 전달합니다.

## 확장 지점
노트북의 Agent 생성 줄에 model_tool=검증한도구 를 연결합니다.
predict(payload)는 modelVersion, trainingCutoff, status, output, limitations를 반환해야 합니다.
기존 Python 계산과 ML/DL 예측은 분리됩니다. 페르소나 literacy=L1~L4,
style=A/C/U는 설명 방식에만 사용하고 실제 수치와 품질 기준을 바꾸지 않습니다.

## 검증 범위
코드와 모의 DB 결과를 이용한 검증입니다. 제작 환경에는 DATABASE_URL이 설정되어 있지 않아
실제 Neon 접속·실제 테이블 값·실제 Solar 호출은 검증하지 않았습니다.

## 추가: 5단계 실행 흐름과 Verifier
품질 상태 확인(조회 상태) → 기업별 입력 검사 → Python 계산·근거 연결 →
LLM 설명(선택) → Verifier 검사 순서입니다. 기존 저장 셀 앞에 Verifier 셀을 추가했습니다.
현재 코드 셀은 총 9개이며 마지막 두 셀은 Verifier, 결과 저장입니다.
Verifier는 입력 해시·버전과 Python 재실행 결과를 비교합니다.
failed: 결과 불일치 또는 구조 오류로 수정 필요.
withheld: 자료 부족에 따른 보류 유지.
review_required: 자동 일관성 검사 후 원문·LLM 의미에 대한 사람 검수 필요.
동일 코드 재현은 독립적인 계산 공식 감사가 아닙니다.
LLM 설명을 자동으로 사실 인증하거나 최종 승인하지 않습니다.
결과 저장에는 verifications도 포함됩니다.

## 추가: 입력 모드·공통 스냅샷·가격 검사·문서 선별 (2026-10-28)
### 입력 모드 (설정 셀의 INPUT_MODE)
| 값 | 의미 |
|---|---|
| wait | 기본값. 조회하지 않고 연결 대기 메시지만 출력 |
| mock | 모의 입력(dataMode=synthetic). 실제 회사·시세가 아니며 코드 동작 확인용 |
| neon | 실제 Neon 조회. 두 Agent 입력을 한 읽기 전용 트랜잭션에서 함께 읽어 공통 스냅샷 생성 |
| snapshot | private_outputs/snapshots의 공통 스냅샷 로드(SNAPSHOT_PATH=None이면 최신 파일) |
실데이터 연결 실패 시 mock으로 자동 전환하지 않습니다.
권장 순서: 한 노트북에서 neon으로 조회(SAVE_SNAPSHOT=True) → 다른 노트북은 snapshot으로 실행.
같은 파일을 읽으면 두 결과의 inputDigest가 같아 compare_results로 비교할 수 있습니다.
스냅샷 파일은 digest로 변조를 검사합니다. DB 원문이 들어 있으므로 공개 저장소에 올리지 마세요.
조회 상한 초과 등 조회 오류는 해당 Agent만 보류합니다(가격 오류가 산업 Agent를 막지 않음).

### source 값 확인
SHOW_SOURCE_VALUES=True이면 neon 조회 전에 rag.document의 실제 source 값·건수·제목 예시를 표로 보여줍니다.
허용 목록(SOURCES)에 없는 값은 조회하지 않습니다. 담당자와 확인한 뒤 SOURCES를 조정하세요.

### 산업: 문서 선별과 사업의 내용 절
- 제목 규칙: 사업보고서(10-K/20-F) > 반기보고서 > 분기보고서(10-Q) > IR. 기업당 최대 3건.
- 감사보고서·주요사항보고서·뉴스 등은 제외 사유와 함께 표시합니다. 같은 기간 정정본은 최신본만 사용합니다.
- 본문 조각은 chunk_idx 순서로 100개씩 나눠 읽고, 문서당 2,000조각을 넘으면 truncated로 보류합니다.
- 정기보고서는 'II. 사업의 내용'(SEC: Item 1. Business) 절 안의 조각만 근거로 씁니다.
  목차 항목은 건너뜁니다. 절을 찾지 못한 문서는 근거에서 빼고 품질 표에 '일부 가능'으로 표시합니다.
- 근거 location.section에 절 제목·하위 절(예: 2. 주요 제품 및 서비스)·문자 범위를 기록합니다.
- 경쟁 표는 키워드가 일치한 후보 발췌만 보여줍니다. 경쟁 강도 평가가 아닙니다.
- 절 탐지는 제목 형식에 의존합니다. 실제 DB 원문 형식은 시범 기업으로 확인해야 합니다.

### 기술적: 가격 검사
- OHLC 논리(고가≥시가·종가≥저가>0) 위반 → 보류.
- 전일 종가 대비 ±30%(KRX 가격제한폭, 호가 여유 0.5%) 초과 → 기업행위로 설명되지 않으면 보류,
  기업행위일과 일치하면 일부 가능. 수정주가(split_adjusted)인데 분할일 급변이 남아 있으면 보류.
- TRADING_CALENDAR_CSV(열: date[,market]): 보유 구간 안의 누락·달력 밖 날짜 → 보류.
- CORPORATE_ACTIONS_CSV(열: ticker,date,type,source): type은 split, reverse_split, bonus_issue,
  rights_issue, dividend, merger, spin_off, capital_reduction, listing, trading_halt, other 중 하나.
  source(확인 출처)가 비어 있으면 읽지 않습니다.
- CSV를 주지 않으면 해당 검사는 '일부 가능'으로 남습니다. 요일로 거래일을 추정하지 않습니다.
- 등록되지 않은 시장(예: US)은 가격제한폭 검사를 생략하고 '일부 가능'으로 표시합니다.

### 보류와 저장
- 보류된 결과는 Agent를 직접 호출해도 LLM·ML/DL을 부르지 않습니다.
- Verifier 결과가 하나라도 failed이면 결과 저장을 차단합니다.

### 아직 확인하지 못한 것
실제 Neon 접속, 실제 source 값과 문서 제목 형식, 가격 조정 기준 출처, KRX 공식 거래일 달력,
기업행위 자료는 모두 미확인입니다. 위 검사는 모의 입력과 테스트로만 확인했습니다.
