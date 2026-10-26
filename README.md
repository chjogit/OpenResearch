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

```bash
git clone https://github.com/chjogit/OpenResearch.git
cd OpenResearch
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env    # 값 채우기 (docs/DB_READONLY.md 참고)
pytest
```

## 일하는 방식

[CONTRIBUTING.md](CONTRIBUTING.md) 를 먼저 읽어 주세요. 요약하면 main에 직접 push하지 않고, 브랜치를 만들어 PR을 올린 뒤 팀원 1명 리뷰를 받고 합칩니다.

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
