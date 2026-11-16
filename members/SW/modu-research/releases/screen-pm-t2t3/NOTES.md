# T2·T3 — 계정별 기록 · 초대 코드 가입·동의 · AI 길잡이 사용 한도 (PM 2026-11-15)

원칙: **엔진 코드는 바꾸지 않음.** 모두 화면(Django) 쪽에서. 엔진은 원래 「owner 쿠키 값 = 한 사람」으로 기록을 나누므로, 화면이 로그인한 계정마다 고정된 owner 값을 대신 보냄.

## 바뀐 것
| 영역 | 내용 | 파일 |
|---|---|---|
| T2 계정별 기록 | 로그인한 계정은 `hmac(SECRET_KEY 또는 MRN_OWNER_SALT, 회원번호)` 앞 32자를 엔진 owner로 보냄 → 어느 PC에서든 같은 계정은 같은 기록, 계정끼리는 안 섞임. 로그인 안 한 사람은 예전처럼 브라우저 쿠키. `MRN_LEGACY_OWNER_USERS`의 아이디는 브라우저 쿠키를 그대로 써 예전 기록 유지 | accounts/usage.py, pages/engine_proxy.py |
| T2 로그인 문 | `MRN_REQUIRE_LOGIN=True`면 근거 리서치·전문가 모드·`/api/`·`/engine/expert`는 로그인한 사람만(배포용). 로그인 뒤 원래 화면으로 돌아감(다른 사이트 주소는 무시) | pages/views.py, accounts/views.py |
| T2 가입 | 동의(이용 안내·개인정보·연구용 시연 고지, 동의문 v1) 필수 + 기록(Consent). `MRN_INVITE_CODES`가 있으면 초대 코드 필수. 받는 정보는 아이디·비밀번호(해시)뿐 | accounts/forms.py·views.py·models.py, signup.html |
| T3 AI 한도 | 사람마다 하루 호출 `AI_DAILY_CALLS`(30) · 하루 AI 응답 시간 `AI_DAILY_SECONDS`(600초) · 전체 이번 달 `AI_MONTHLY_CALLS`(3000). 먼저 닿는 쪽에서 멈춤 → AI 없이 규칙으로만 찾고 이유 표시. 실제로 AI를 부른 답만 셈(규칙 답·실패는 안 셈). 대상: `/api/guide/translate`, `/api/agent/plan` | pages/engine_proxy.py, accounts/usage.py |
| 화면 | AI 길잡이 칸에 「오늘 남은 AI 길잡이 n회 · m분」, 한도에 닿으면 이유 | research.js |
| 관리자 | /admin/ 에서 「가입 동의」·「AI 사용량」 보기 | accounts/admin.py |
| 시연 켜기 | 화면을 켜기 전에 `manage.py migrate` (표가 이미 있으면 아무것도 안 함) | _screen_jt/시연_열기.ps1 |

## 시험
- 새 시험 17개(accounts/test_t2t3.py) 모두 통과 · 기존 시험 27개 중 26개 통과
- 실패 1개 `test_temporary_public_address_can_post`는 **이 변경 전에도 실패**(확인함): PM PC `.env`에서 Cloudflare 공개 주소를 일부러 막았기 때문(보안 결정). 배포 때 `.env`에 맞춰 시험을 고칠 예정
- 실제 엔진과 함께: 계정 A가 실행 1건 → A에게 1건, B에게 0건. AI 미설정 엔진의 규칙 답은 사용량에 안 셈

## 정한 것(J번호, 되돌릴 수 있음)
- J34 「하루 사용 시간」 = AI 응답에 걸린 시간 합계(비용과 비례). 화면에 머문 시간이 아님
- J35 기본값: 하루 30회 · 하루 10분 · 이번 달 전체 3000회
- J36 PM PC는 `MRN_REQUIRE_LOGIN=False`(시연 편의) · AWS는 True
- J37 이메일을 받지 않음(최소 수집). 비밀번호 분실 시 운영자가 관리자 화면에서 재설정

## 되돌리기
before/ 의 파일을 제자리에 덮고, 새 파일(accounts/models.py·admin.py·usage.py·test_t2t3.py·migrations/)을 지우기 전에 `manage.py migrate accounts zero`.
