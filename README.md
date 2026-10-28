# OpenResearch

KIC AI Agent 공모전 4인 팀의 **금융 리서치 AI Agent** 저장소입니다.
전문가(애널리스트·심사역)에게는 반복 업무 자동화와 검증된 보고서 초안을, 입문자에게는 단계별 분석 순서와 용어 해설을 주는 듀얼 모드 Agent를 만듭니다.

- 데이터 수집은 별도 저장소 [chjogit/kic-agent-data](https://github.com/chjogit/kic-agent-data) 가 GitHub Actions로 매시간 Neon Postgres에 적재합니다.
- 이 저장소는 그 DB를 **읽기 전용**으로 조회해 분석·보고서를 만듭니다. 이 저장소에서 DB에 쓰지 않습니다.

## 4대 원칙

1. **숫자 생성 금지**: LLM은 재무 수치를 계산·추정하지 않습니다. 모든 수치는 `core` 스키마를 조회한 도구 결과만 인용합니다.
2. **Verifier 통과 필수**: 초안의 모든 수치를 `fact_source_verifier` 가 도구 실행 로그와 1:1 대조하고 출처 태그(`[출처: Neon core]`, `[출처: DART 2026.Q3]`)를 붙입니다. 불일치하면 다시 계획합니다.
3. **투자 권유 표현 금지**: "매수/매도 추천" 대신 "투자 검토 참고치 및 리스크 요약"으로 씁니다.
4. **듀얼 모드**: 같은 도구 결과로 전문가 모드(간결한 수치·비교)와 가이드 모드(지표 정의·Peer 선정 이유·분석 순서)를 출력합니다.

## 구조

```
agent/
  config.py            환경 변수 읽기
  db.py                Neon 읽기 전용 접속 (SELECT만 허용)
  llm.py               Upstage Solar 모델 생성
  tools/
    core_finance_peer_analyst.py   TTM 재무·Peer 멀티플 (P0)
    dart_sec_risk_examiner.py      부실 징후 4종·공시 청크 (P0)
    macro_sentiment_tracker.py     거시·감성 스냅샷 (P1)
  verifier/
    fact_source_verifier.py        초안 수치 대조·출처 주입 (P0)
  prompts/
    expert.md          전문가 모드 지침
    guide.md           가이드 모드 지침
members/             팀원별 작업 폴더 (CH, SW, SH, JT)
docs/
  DB_READONLY.md       팀원 DB 읽기 전용 접속 안내
  DATA_MAP.md          Agent가 쓰는 Neon 테이블·뷰 요약
tests/
```

## 시작하기

Python 3.12 을 씁니다. PC 기본 Python 이 다르면 uv 로 가상환경만 3.12 로 만듭니다 (PC 설정은 그대로).

```bash
git clone https://github.com/chjogit/OpenResearch.git
cd OpenResearch
pip install uv
uv venv --python 3.12 .venv
source .venv/bin/activate                  # Windows: .venv\Scripts\activate
uv pip install -r requirements-dev.txt
python -m ipykernel install --user --name openresearch --display-name "Python (openresearch .venv)"
cp .env.example .env    # 값 채우기 (docs/DB_READONLY.md 참고)
pytest
```

노트북은 커널을 **Python (openresearch .venv)** 로 골라 실행합니다. 다른 커널(예: 개인 conda 환경)로 열면 패키지가 없어 `ModuleNotFoundError` 가 납니다.

## 일하는 방식

Git 사용 순서는 [docs/GIT_GUIDE.md](docs/GIT_GUIDE.md)(팀원용 따라하기)를 보세요. 협업 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md) 에 있습니다. 요약하면 각자 자기 브랜치에서 작업하고, main 에는 PR 로만 합칩니다.

## 일정

| 단계 | 마감 |
|---|---|
| 예선 기획안(10p PDF) | 2026-11-12(목) 10:00 |
| 본선 데모·최종 코드 | 2026-12-22(화) |

## MVP 우선순위

| 우선순위 | 모듈 | 범위 |
|---|---|---|
| P0 | 기업 리서치 & Peer 비교 | KOSPI 200 TTM 실적, Peer 비교표, PDF/Excel 초안 |
| P0 | 리스크 심사 & Verifier | 부실 징후 4종, 사전심사 의견서 초안, 수치 대조 |
| P1 | 가이드 모드 | 용어 해설, 분석 순서 안내, 되묻기 |
| P1 | 산업·시장 모니터링 | 신규 공시 감지 시 P0 모듈 자동 실행 |
| P2 | TTS 음성 브리핑 | 확장 과제 |

## 페르소나: 금융 이해도 4단계 × 분석 성향 2가지

공통 모듈 agent/personas.py와 두 Agent 연결부 agent/persona_agents.py를 추가했습니다.
L1~L4와 적극형(A)·신중형(C)의 8개 조합, 단일 축 모드, 미정·사용자 확인을 지원합니다.
기존 expert/guide 호출은 유지합니다.

    python -m agent.persona_cli catalog
    python -m agent.persona_cli classify --level L2 --style A --confirmed
    python -m examples.persona_agents

API 키 없이 분류와 입력 메시지를 확인할 수 있습니다.
정의표·설문 규칙·연결 예시는 [docs/PERSONAS.md](docs/PERSONAS.md)를 참고하세요.
실제 모델·DB 실행 및 분류의 실증 검증은 별도입니다.

## 제2판 주장·근거·버전 연결

A기업 합성 예시와 두 Agent의 공통 입력 계약을 추가했습니다.
[구조와 적용 안내](docs/RESEARCH_CONTRACT.md)를 참고하세요.
예시 생성·검증: python -m examples.research_example
실제 자료·LLM 분석·공동 검토 권한 검증과는 구분합니다.

## 산업·사업모델 / 기술적 분석 Agent 노트북 (Neon)

notebooks/01_산업사업모델_Agent_Neon.ipynb, notebooks/02_기술적분석_Agent_Neon.ipynb 를 각각 독립 실행합니다.

    pip install -r requirements-neon-agents.txt

설정 셀의 INPUT_MODE 로 연결 대기(wait)·모의 입력(mock)·실제 조회(neon)·공통 스냅샷(snapshot)을 고릅니다.
품질 검사(OHLC·가격제한폭·거래일·문서 선별·사업의 내용 절) → Python 계산 → 선택 Solar → Verifier 순서입니다.
실행 방법은 [notebooks/Neon_두_Agent_독립실행_안내.md](notebooks/Neon_두_Agent_독립실행_안내.md) 를 보세요.
실제 Neon 접속·Solar 호출은 아직 검증하지 않았습니다.

처음 보는 팀원은 DB·API 키 없이 실행되는 안내 노트북부터 여세요(실행 결과가 저장되어 있어 열기만 해도 볼 수 있습니다).

| 노트북 | 내용 |
|---|---|
| notebooks/03_인수인계_기본구조_둘러보기.ipynb | 페르소나 8조합·설문, 주장·근거·버전 계약, 두 Agent 기본 계산, 품질 검사, Verifier |
| notebooks/04_품질검사_문서선별_공통스냅샷.ipynb | 가격 검사, 공시 문서 선별, 사업의 내용 절 탐지, 공통 스냅샷, 저장 차단 |
| notebooks/05_페르소나_문단분류_관측상태_평가.ipynb | 페르소나 결정·표현, 문단 분류 기준선, 관측 상태 규칙, 페르소나 보존 평가, ML 채택 판단 |
