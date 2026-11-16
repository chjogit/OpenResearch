# 전문가 모드(B+) — PM이 화면에 붙인 변경 (2026-11-13, 휴일이라 PM이 직접 적용)

전태님, 휴일 중이셔서 PM 쪽에서 직접 붙였습니다. 아래 내용 그대로 가져가시면 됩니다. 계산·문장은 엔진 그대로이고, 화면(Django) 쪽만 바뀌었습니다.

## 무엇이 생겼나
- 왼쪽 메뉴에 **「전문가 모드」**(근거 리서치 바로 아래, 아이콘 ti-columns) → `/expert-mode/`
- 화면 틀(왼쪽 메뉴·상단바) 안에 엔진 전문가 모드(흐름 캔버스·노드 조립·실행·근거 지도 등)를 iframe으로 보임
- 엔진 주소(4395)를 브라우저에 직접 열지 않음 → 배포 서버에서도 같은 코드로 동작

## 바뀐 파일 (6곳 고침 + 3개 새 파일)
| 파일 | 내용 |
|---|---|
| stocknote/urls.py | `engine/expert`, `engine-static/<name>` 주소 2줄 |
| pages/urls.py | `expert-mode/` (name=expert_mode) |
| pages/views.py | `expert_mode()` 끝에 추가 |
| pages/engine_proxy.py | 끝에 `expert_page()`, `engine_static()` 추가 (기존 `forward()`는 그대로) |
| pages/templates/pages/base.html | `URLS.expert_mode` 1줄 |
| pages/static/pages/js/common/layout.js | MENU 1줄 |
| (새) pages/templates/pages/expert-mode.html | 화면 틀 + iframe |
| (새) pages/static/pages/css/pages/expert-mode.css | 본문 넓게, iframe 높이 |
| (새) pages/static/pages/css/pages/expert-skin.css | iframe 속 엔진 화면 덧입힘(대표색 베리·바탕·글꼴, 모드 막대 숨김) |

## engine_proxy 추가분이 하는 일
- `/engine/expert`: 엔진 `/expert`를 받아 `/static/` → `/engine-static/`, 쉬운 화면 링크 → `/research/`(target=_top), skin CSS 삽입, `body.in-shell`. `@xframe_options_sameorigin`(같은 사이트 안에서만 iframe 허용).
- `/engine-static/<name>`: 이름은 `영문·숫자·._- + .css/.js`만 받음(다른 경로 차단). app.js의 답 카드 링크 `/#answer=번호` → `/research/#/answer/번호`(target=_top).
- API 호출(`/api/...`)은 기존 `forward()` 그대로. 엔진 쿠키·X-CSRF-Token 규칙 변경 없음.

## 지킨 것
- 색: 대표색(주황→베리)·바탕·글꼴만 바꿈. 값 종류 색(--k-*), 관점 색(--p-*), 실행 상태 색은 뜻이 있어 그대로.
- 외부 요청 0: 로컬 글꼴·아이콘만 씀.
- 엔진 코드 변경 없음.

## 확인한 것 (VM 시험 사본)
- `/expert-mode/` 200, 메뉴 항목 표시
- `/engine/expert` 200, X-Frame-Options SAMEORIGIN, 엔진 css·js 4개 모두 200
- app.js 답 카드 링크 3곳 모두 /research/#/answer/ 로 바뀜
- 잘못된 파일 이름 404
- 프록시 경유 `/api/health` 200, POST(`/api/validate`) CSRF 포함 200
- 패치 두 번 돌려도 같은 결과(표식 「B+ 전문가 모드」)

## 되돌리기
`before/` 폴더의 6개 파일을 제자리에 덮고, 새 파일 3개를 지우면 원래대로입니다.
적용: `python patch_bplus.py <manage.py 있는 폴더>`

---
# 추가: 시연에서 숙련자 홈 빼기 (PM 결정 2026-11-13)
이유: 숙련자 홈은 임시 데이터이고, AI 신호가 있고, 출처가 없어 시연에 맞지 않음.
- `core.js`: 숙련자 모드일 때 홈 주소 = 근거 리서치 (모드 선택·퀴즈·학습 끝·첫 화면 버튼 모두 근거 리서치로 이동)
- `layout.js`: 숙련자 모드일 때 왼쪽 메뉴의 '숙련자 홈' 숨김
- 입문자 모드는 그대로. 숙련자 홈 파일·주소(/home-expert/)는 지우지 않음
- 적용: `python patch_demo_hide_expert_home.py <화면 폴더>` (표식 「시연: 숙련자 홈 숨김」)
- 되돌리기: `before_demo/`의 core.js·layout.js를 제자리에 덮기
- 확인: 모드 선택에서 「투자 경험이 있어요」 → 근거 리서치로 이동, 메뉴에 숙련자 홈 없음 (PM PC 화면에서 확인)

---
# 추가: 시연에서 「AI에게 질문」 숨기고 질문은 근거 리서치로 (PM 결정 2026-11-15)
이유: 「AI에게 질문」은 아직 AI에 연결되지 않은 임시 화면(정해 둔 예시 질문에만 답). 심사위원이 위쪽 검색창에 아무 질문이나 치면 「임시 응답」이 나옴.
- `core.js`: `URLS.chat = URLS.research` — 위쪽 검색창, 용어 사전·기초 학습·입문자 홈의 「AI에게 물어보기」가 모두 근거 리서치로 감
- `layout.js`: 왼쪽 메뉴에서 「AI에게 질문」 숨김, 검색창 안내 문구 「회사 이름이나 궁금한 것을 근거로 찾기」
- `research.js`:
  - `?q=글`을 받는 `takeTopQuery()` 추가 — 회사 이름·종목코드가 있으면 그 회사를 고르고, 남은 글은 「자유 질문」 해석까지(실행은 사람이 「이대로 조사」를 눌러야 함). 회사 이름 일부(예: 삼성)면 회사 고르기 목록을 띄움
  - 「전문가 모드 열기」를 엔진 주소(새 창) → 화면 틀 안 전문가 모드(`URLS.expert_mode`)로
- 화면 파일·주소(/chat/)는 그대로. 나중에 Claude API로 「AI에게 질문」을 실제 연결하면 이 패치를 되돌림
- 적용: `python patch_demo_search_to_research.py <화면 폴더>` (표식 「시연: AI에게 질문 숨김」)
- 되돌리기: `before_demo2/`의 core.js·layout.js·research.js를 제자리에 덮기

---
# 추가: AI 길잡이를 「자유 질문」에 실제로 잇기 (PM 2026-11-15, Claude API 연결)
- 전에는 「AI 길잡이 켜기」가 켜짐 표시만 저장하고, 질문할 때 부르는 곳이 없었음(엔진 원래 화면 easy.js의 guideOffer/guide가 옮겨지지 않음)
- `research.js`: 길잡이가 켜져 있으면 자유 질문 결과 아래에 「AI 길잡이에게 바꿔 달라고 하기」 → `/api/guide/translate`(use_model) → AI가 바꾼 질문·가까운 카드·규칙 후보. 실행은 사람이 누름. 숫자·판단은 엔진이 걸러 냄
- 적용: `python patch_demo_ai_guide.py <화면 폴더>` (표식 「시연: AI 길잡이 연결」) · 되돌리기: `before_demo3/research.js`
- 이 부분은 시연용이 아니라 계속 둘 기능입니다(전태님 화면에 정식으로 넣어 주세요)

---
# 추가: 시연 전 작은 흠 정리 (PM 2026-11-15)
- `research.js` `fmtCut()`: 「기준 날짜」를 한국 시각으로 (답 카드 머리·나란히 보기·근거 서랍 3곳). `…T16:00:00+09:00` → 「YYYY-MM-DD 장 마감(16:00)」, 그 밖의 시각 → 「YYYY-MM-DD HH:MM (한국 시각)」
- 답 카드 제목: 회사 이름이 없으면(전문가 모드에서 여러 회사를 섞은 흐름) 앞의 「 · 」 빼기 · 값 종류가 비면 빈 칩을 그리지 않음
- `layout.js`: 「화면의 수치는 임시 데이터입니다.」를 근거 리서치·전문가 모드에서만 숨김(실제 엔진 화면)
- 적용: `patch_demo_polish.py`(표식 「시연: 작은 흠 정리」), `patch_demo_polish2.py`(표식 「시연: 빈 칩 숨김」) · 되돌리기: `before_demo4/`
- 참고: 브라우저가 예전 JS를 기억할 수 있으니 바꾼 뒤에는 Ctrl+F5
- 추가: 첫 화면(랜딩) 검색칸이 템플릿에 `/chat/`을 직접 적고 있어 근거 리서치로 바꿈(`patch_demo_landing.py`, 표식 「시연: 첫 화면 검색 → 근거 리서치」, 원본 `before_demo4/index.html`)
