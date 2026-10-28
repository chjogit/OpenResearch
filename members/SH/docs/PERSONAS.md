# 금융 페르소나 분류 및 Agent 적용

## 저장소 확인 결과와 범위

기준 커밋: 429ad2d0d7888be2e50efff057e0e50f2064bee1.
공통 agent/에는 SQL 도구·수치 검증기·expert/guide 프롬프트가 있다.
members/CH/solar_pro_4.py에는 산업·사업모델(3번), 기술적 분석(5번)을 포함한
6+1 분석·첨삭 파이프라인이 있다. 이 두 Agent에 공통 페르소나 정책을 연결했다.
다른 관점 Agent는 기존 모드를 유지하며 최종 종합에는 페르소나 설명 정책을 전달한다.
기존 mode 인자와 페르소나 미지정 호출은 그대로 유지한다.

## 분류 체계

| 이해도 | 정의 | 설명 |
|---|---|---|
| L1 입문 | 용어·기본 구조 학습 | 쉬운 말·비유·용어 해설 |
| L2 기초 | 개별 지표 의미 이해 | 의미→기업 사례→주의점 |
| L3 중급 | 자료·지표 비교·연결 | 비교표·관계·반대 해석 |
| L4 고급 | 가정·산식·편향·한계 검토 | 방법론·조건·민감도·반증 |

| 분석 성향 | 정의 | 표현 |
|---|---|---|
| A 적극형 | 기회 성립 조건 우선 검토 | 기회를 먼저, 실패 조건·위험도 함께 |
| C 신중형 | 지속 가능성·위험 우선 검토 | 위험을 먼저, 기회·완화 근거도 함께 |

복합 유형은 L1-A, L1-C, L2-A, L2-C, L3-A, L3-C, L4-A, L4-C의 8개다.
이해도만 4개·성향만 2개·복합 8개의 정의는 persona_catalog.json 및 persona_definitions.csv에 있다.
LX는 미정/비적용 이해도, U는 중립/미정/비적용 성향이다. 사용자 유형을 강제로 채우지 않는다.

이것은 설명·분석 관점 설정이며 투자 적합성·실제 손실 감내 능력 판정이 아니다.
이해도와 자산·소득·수익률, 성향과 투자기간·자금여력을 동일시하지 않는다.

## 공통 모듈

- sh_agents/personas.py: enum, 불변 프로필, 정의표, 설문 제안, 사용자 확인, 정책.
- sh_agents/persona_agents.py: 기존 industry_bm_data / technical_data 입력 메시지 연결.
- sh_agents/persona_cli.py: 카탈로그·질문·분류·정책 확인용 CLI.
- examples/persona_agents.py: 가상 자료로 두 Agent 입력 확인.
- tests/test_personas.py: 8개 조합·미정·잘못된 입력·규칙 경계·자료 보존.
- tests/test_persona_ch_integration.py: 실제 CH 분석·첨삭·종합 호출 경로, SDK는 mock.

프로필과 정책만 처리하며 수집기·DB 권한·Neon 데이터를 변경하지 않는다.
모듈을 import할 때 DB·LLM·API 키가 필요하지 않다.
프로필·확인시각·사용자·정의버전·변경이력의 영구 저장은 호출하는 앱 담당이다.
confirmed는 사용자가 확인한 뒤 앱이 설정해야 한다. 현재 CLI/모듈은 인증·동의 UI를 제공하지 않는다.

## 자기선택 및 사용자 확인

    from sh_agents.personas import PersonaProfile, confirm_persona

    proposed = PersonaProfile("L2", "A")
    # 사용자에게 제안 결과를 보여주고 수정·확인을 받은 뒤:
    confirmed = confirm_persona(proposed)
    payload = confirmed.to_dict()
    restored = PersonaProfile.from_dict(payload)

분류 상태는 suggested / user_confirmed / unresolved이다.
확인 전에는 제안 코드만 보관하고 실제 정책은 기본 L2 설명·중립 관점으로 처리한다.
확인된 부분 분류(예: L2-U)는 이해도만 적용하고 다른 축은 중립으로 유지한다.
mode는 combined, literacy_only, style_only다.
선택한 mode 밖의 축을 함께 전달하면 실수 방지를 위해 ValueError로 거절한다.

    python -m sh_agents.persona_cli catalog
    python -m sh_agents.persona_cli questions
    python -m sh_agents.persona_cli classify --level L2 --style A --confirmed
    python -m sh_agents.persona_cli prompt --level L1 --style C --confirmed --domain technical_analysis
    python -m examples.persona_agents

기존 expert/guide를 사용자가 진단받은 등급으로 자동 치환하지 않는다.
명시적인 from_legacy_mode()는 expert→L4, guide→L1 제안만 반환하며 확인 전 정책은 중립이다.

## 설문 분류 규칙 (초기 실험용, 검증된 척도가 아님)

get_questionnaire()는 지식 8문항·성향 4문항을 반환하며 정답 키는 반환하지 않는다.
코드 내부 정답은 보안 경계가 아니다. 제품 진단일 뿐 시험 부정행위 방지 시스템은 아니다.

- 지식: 모든 문항 완료 시 정답 수 0~2=L1, 3~4=L2, 5~6=L3, 7~8=L4.
- 지식 미완료: 부분 점수로 상위·하위 등급을 추정하지 않고 미정.
- 성향: A/C/U 선택, 3문항 이상 응답하고 A/C 표 차이가 2 이상이면 다수 유형 제안.
- 답변 부족·동률·불분명한 성향은 U. 실제 투자성향을 확정하는 통계 모델이 아님.
- 모든 설문 결과는 제안이며 requires_user_confirmation=True.
- 단일 이해도 점수의 영역별 편차·문항 타당도·사용자 오분류를 추후 검증해야 함.

    from sh_agents.personas import assess_questionnaire, PersonaProfile
    result = assess_questionnaire(knowledge_answers={"K1": "b"},
                                  style_answers={"S1": "A", "S2": "C"})
    proposal = PersonaProfile.from_dict(result["profile"])
    # 부족한 답변은 LX-U로 남는다. 먼저 추가 질문 또는 사용자 자기선택을 받는다.

설문 JSON 파일은 knowledge_answers, style_answers, mode 필드만 받는다.
python -m sh_agents.persona_cli assess docs/persona_questionnaire_example.json

## 두 Agent 연결

1. 독립 호출:

       from sh_agents.persona_agents import build_industry_messages, build_technical_messages
       industry_messages = build_industry_messages(context, confirmed)
       technical_messages = build_technical_messages(context, confirmed)

반환값은 role/content 딕셔너리 목록이다. source가 있는 관점 자료가 필요하다.
메시지 생성은 데이터의 깊은 복사본을 직렬화하며 원본 수치·결측·출처를 바꾸지 않는다.
실제 모델 결과를 검증한 보고서가 아니라 모델에 전달할 입력이다.

2. 기존 CH 파이프라인:

   > 주의(2026-10-28): main에서 members/CH/solar_pro_4.py가 삭제되고 members/CH/ch_agents로 대체되었습니다.
   > 아래 연결 예시와 tests/test_persona_ch_integration.py는 이전 파일 기준이라 이 브랜치에서 제외했습니다.
   > ch_agents에 페르소나를 연결하는 작업은 CH 담당자와 별도로 정합니다.


       from members.CH.solar_pro_4 import run_openresearch_multi_agent, review_report
       result = run_openresearch_multi_agent("005930", mode="expert", persona=confirmed)
       review = review_report("검토할 보고서", ticker="005930", persona=confirmed)

기존 개인 실행 파일 의존성은 requirements-member-ch.txt로 설치한다.
실제 실행에는 기존 DATABASE_URL·UPSTAGE_API_KEY 설정이 필요하다.
이 변경에서는 외부 DB 및 유료 모델을 호출해 검증하지 않았다.
프로필을 전달하지 않으면 기존 expert/guide 호출과 결과 키를 유지한다.
저장소 루트에서 Python import 또는 모듈 실행을 권장한다.

## 불변 정보와 검증 한계

페르소나로 달라지는 것은 설명·용어·깊이·순서·확인 질문뿐이다.
수치·출처·기준일·위험·불확실성·자료 부족·지표 설정은 동일하게 유지하도록 지시한다.
산업 경쟁강도 자료가 없으면 판단 보류, 기술적 지표는 코드 계산값만 해석한다.
통제된 enum 외의 자유 문구는 페르소나 정책에 삽입하지 않는다.

단, 프롬프트 지시만으로 실제 LLM 출력의 불변성을 보장할 수는 없다.
공용 fact_source_verifier 등으로 모델 출력의 수치·출처를 반드시 재검토해야 한다.
기존 CH의 FactSourceVerifier는 출처 각주를 추가하는 구현이며 완전한 사실 검증기가 아니다.
해당 기존 수집·폴백·검증기의 동작을 이번 페르소나 변경에서 재설계하지 않았다.
검증용 스냅샷을 실제 자료로 오인하지 않도록 후속 실행·UI에서 구분해야 한다.
원천 문서의 명령문을 지시로 따르지 말라는 정책은 보조 수단이며 입력 격리·도구 권한은 별도다.

## 검증과 팀 통합

    pytest -q
    ruff check .

단위·mock 테스트는 모델 품질·산업 판단·차트 예측 정확도·DB 연결을 입증하지 않는다.
다음 검증은 동일 원천 자료에서 8개 설명의 사실·위험 유지 여부, 사용자 등급 수정률,
설명 이해도, 근거 적합성, 투자성향 중립 처리의 적절성이다.
공용 코드 변경이므로 CONTRIBUTING.md에 따라 팀원 리뷰 후 PR로 main에 합친다.

## 두 Agent 적용 순서 (2026-10-28)

노트북 01(산업)·02(기술적)에서 아래 순서로 동작합니다. 모든 단계는 DB·LLM 없이 모의 입력으로 확인했습니다.

### 1. 페르소나 결정
설정 셀에서 직접 선택(`LITERACY`, `STYLE`) 또는 기존 설문(`KNOWLEDGE_ANSWERS`, `STYLE_ANSWERS`) 중 하나를 씁니다.
- 직접 선택은 사용자 확인으로 봅니다. 설문 결과는 `CONFIRM_QUESTIONNAIRE=True`일 때만 적용하고, 그 전에는 L2·중립(U)으로 표시합니다.
- `select_persona()` → `AgentSettings.from_persona()` (sh_agents/basic_agents.py)
- 결과의 `presentation`(sh_agents/persona_presentation.py)이 제시 순서·상세도·용어 풀이(L1·L2)·확인 질문을 정합니다.
- 적극형은 기회 절을, 신중형은 위험 절을 앞에 둡니다. 어느 쪽도 다른 절을 빼지 않습니다.
- LLM을 쓰면 같은 규칙이 시스템 지시로 전달됩니다.

### 2. 산업 Agent: 문단 분류 기준선
- 결과의 `paragraphClassification`은 키워드 규칙(`paragraph-keyword-1`) 결과이며 `unreviewed`입니다.
- 저장 셀의 `EXPORT_LABEL_SHEET=True`로 `private_data/paragraph_labels/labels_*.csv`를 만듭니다. 규칙 예측은 넣지 않습니다(앵커링 방지).
- 사람이 `human_label`(아래 코드 또는 한글 이름)과 `labeler`를 채웁니다. 의견이 갈리면 합의한 한 줄만 남깁니다.

| 코드 | 이름 |
|---|---|
| business_overview | 사업 개요 |
| products_services | 제품·서비스 |
| revenue_orders | 매출·수주 |
| customers | 고객·판매처 |
| suppliers_materials | 원재료·공급·생산설비 |
| competition | 경쟁·시장점유율 |
| barriers_regulation | 진입장벽·규제·특허 |
| rnd_contracts | 연구개발·주요계약 |
| risk_management | 위험관리·파생거래 |
| other | 기타·분류 불가 |

- `load_labels()` → `evaluate()`로 정확도·macro F1·분류별 정밀도/재현율·혼동 쌍을 봅니다.
  정답 50문단 미만이거나 문서 3건 미만이면 경고가 붙습니다.
- 평가 데이터는 `split_by_document()`로 문서 단위로 나눕니다(같은 공시의 문단이 학습·평가에 섞이지 않게).

### 3. 기술 Agent: 관측 상태 규칙
기존 계산값에 설명용 구간을 붙입니다(sh_agents/technical_states.py, `technical-states-1`). 예측·매매 신호가 아닙니다.

| 상태 | 규칙 |
|---|---|
| 추세 | 종가/SMA−1이 ±1% 미만이면 "이동평균 부근", 그 외 위/아래 |
| 수익률 | 절댓값 3% 미만 작은 변동, 10% 미만 뚜렷한 변동, 그 이상 큰 폭 변동 |
| 변동성 | 최근 window 수익률 표준편차 ÷ 전체 기간(관측 2×window 이상일 때만): 0.67 미만 축소, 1.5 초과 확대 |
| 거래량 | 직전 window 평균 대비 −50% 이하 감소, +50% 이상 증가, +100% 이상 급증 |

임계값은 검증 전 초기 규칙입니다. 바꾸면 RULE_VERSION을 올립니다.

### 4. 평가: 페르소나 변경 전후 보존
Verifier 셀이 `evaluate_persona_invariance()`로 12개 설정(L1~L4 × A/C/U)을 같은 입력·품질 판정으로 다시 실행합니다.
수치·근거·주장·품질 판정·보류 상태·입력이 중립(L2-U)과 하나라도 다르면 `failed`입니다.
Verifier에도 "페르소나 불변" 검사가 들어 있습니다. 설명 문장의 품질이나 LLM 출력은 평가하지 않습니다.

### 5. ML 확장 판단
`sh_agents/model_comparison.py`의 `compare()`는 아래를 모두 만족할 때만 모델 채택을 제안합니다. 모델 학습은 하지 않습니다.
- 규칙 기준선에 약점이 있음(지원 5문단 이상인 분류의 F1 < 0.6)
- 기준선과 모델이 같은 평가 정답셋(goldDigest), 학습 정답셋과 평가 정답셋이 다름
- 평가 문단 50개 이상, macro F1이 0.05 이상 개선, 어떤 분류도 0.05 넘게 나빠지지 않음
- 모델 정보(modelVersion, trainingCutoff, trainingGoldDigest) 기록
최종 채택은 사람이 결정합니다.
