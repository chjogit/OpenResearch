# v0.39.1 — PM 요청 작은 수정 모음 (v0.39 발송 2026-11-13 뒤)

기준: 보낸 v0.39(엔진 묶음 c4679673be37 · 인계 0c90af600b4d)와 같은 엔진 파일에서 시작. 이 폴더의 패치는 모두 그 위에 「더하기만」.
- 고치기 전 파일은 before/에(처음 고칠 때 한 번만), 통째로 새로 만드는 파일은 new/에.
- 패치마다: 고칠 곳을 먼저 모두 확인 · 하나라도 못 찾으면 아무것도 바꾸지 않음 · 두 번 돌려도 같음 · 시험 · 되짚기(verify_rebuild.py).
- 전태님 회신이 v0.39 문제를 말하면: 보낸 v0.39(= before/ + _releases/v0.39-t3) 기준으로 가르고, 이 폴더 수정과 섞이지 않게 v0.39.1에 함께 담음.

## 수정 목록 (요청 → 패치 → 확인)
| 번호 | 요청(PM 말 그대로 요약) | 파일 | API·숫자 영향 | 패치 | 확인 |
|---|---|---|---|---|---|
| 1 | R11 전태님 REQUESTS(2026-11-13): 카드 짧은 이름 11개를 화면 이름표로 | mrn/easy.py `SHORT` | API `/api/easy/cards`의 `cards[].short` **값(글자)만** 바뀜, 칸·title·계산 영향 없음. 엔진 안에서 short를 쓰는 곳은 카드 목록 응답 하나뿐(쉬운 화면·전문가 모드·MCP는 안 씀) | patch_r11.py · tests/test_v0391_r11.py(3) | 전체 578개 통과(건너뜀 1) · 되짚기 통과 · API 응답 11개 확인 |
| 2 | R12 PM(2026-11-15): Claude API 연결 — Claude 최신 모델이 `temperature`를 거절(HTTP 400 「temperature is deprecated for this model」, 점검기 `_releases/claude-link/ai-check.cmd`로 확인) | mrn/guide.py `_call_model`, mrn/planner.py `model_plan` (각 1곳) | 모델 이름이 claude로 시작하면 temperature 빼기, 모든 모델에 max_tokens 1024. 로컬 모델(exaone 등)은 temperature 0 그대로. API 모양·숫자 영향 없음 | patch_r12.py · tests/test_v0391_r12.py(3) | 전체 581개 통과(건너뜀 1) · 되짚기 통과 |
