# 협업 규칙

## 브랜치

- `main` 은 항상 실행되는 상태로 둡니다. 직접 push하지 않습니다.
- 각자 자기 브랜치(`ch`, `sw`, `sh`, `jt`)에서 작업하고, 퇴실 전 push 후 PR 로 main 에 합칩니다. 순서는 [docs/GIT_GUIDE.md](docs/GIT_GUIDE.md).

## PR

1. 작업 브랜치에서 커밋 후 push → GitHub에서 PR 생성.
2. PR 템플릿의 체크리스트를 채웁니다 (특히 "숫자 생성 금지", "투자 권유 표현 없음").
3. CI(`pytest`, `ruff`)가 통과하면 합칩니다. 공용 코드(`agent/`)를 바꾼 PR 은 팀원 1명이 확인한 뒤 합칩니다.
4. 개인 브랜치는 지우지 않고 계속 씁니다.

## 커밋 메시지

한국어로 무엇을 왜 바꿨는지 한 줄로 씁니다. 예: `Peer 비교표에 EV/EBITDA 열 추가`

## 비밀값

- `.env` 는 절대 커밋하지 않습니다. 새 변수는 `.env.example` 에 이름만 추가합니다.
- DB 접속 주소·API 키를 이슈, PR, 채팅에 붙여 넣지 않습니다.

## 역할 분담 (예시, 팀 회의에서 확정)

| 담당 | 모듈 |
|---|---|
| 팀원 A | `core_finance_peer_analyst`, Peer 비교표·보고서 출력 |
| 팀원 B | `dart_sec_risk_examiner`, 사전심사 의견서 |
| 팀원 C | `fact_source_verifier`, 오케스트레이션(LangChain) |
| 팀원 D | 가이드 모드 프롬프트, `macro_sentiment_tracker`, 데모 UI |

담당이 정해지면 `.github/CODEOWNERS` 에 GitHub 아이디를 넣어 해당 폴더 PR에 자동으로 리뷰 요청이 가게 합니다.
