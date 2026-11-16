# SW 작업 폴더 — 모두의리서치 (PM)

PM(SW)이 만든 **모두의리서치 엔진 + 화면 통합 + 운영 도구**의 코드입니다. 기준판: 엔진 v0.39.5 (2026-11-16).
공개 저장소이므로 **코드·시험·문서만** 올립니다. 자료(Neon 사본, KIS 시세·수급, 증권사 보고서 PDF, DB 파일)와 키는 없습니다.

## 무엇이 들어 있나 (`modu-research/`)
| 폴더 | 내용 |
|---|---|
| `engine/` | 엔진(FastAPI, `mrn/`) · 시험(`tests/`, 약 600개) · 전문가 모드 화면(`web/`) · 실행 스크립트(`setup.cmd`·`start.cmd` 등) · 키 예시(`local-env.example.cmd`) |
| `tools/` | 가격 갱신(KIS 일별 종가) · **수급 갱신(KIS 투자자별 매매, Plan B)** · 백업(코드·DB, 원천 자료 보관본) · Neon 사본 받기 · DART 원문 · 데이터랩 · 설명 영상용 음성(ElevenLabs)·화면 자동 녹화 · 이 묶음 만들기(`pr_pack`) |
| `releases/` | 버전별 변경 기록(NOTES)과 패치 스크립트, 화면 통합 패치(`screen-pm-*`: 전문가 모드 통합, 가입·동의·AI 사용량 한도, 공시함, 여러 회사 비교·엑셀, 보고서 초안 등) |
| `launchers/` | PM PC용 시연 켜기·끄기·갱신 실행 파일(경로는 PM PC 기준) |
| `PACK_MANIFEST.txt` | 담은 파일 전부의 크기·sha256 |

- 화면(Django) 본체는 JT(전태님) 작업이라 여기 넣지 않았습니다. 여기에는 PM이 그 위에 얹은 **통합 패치**만 있습니다.

## 원칙 (OpenResearch 4대 원칙과 같음)
1. **숫자는 앱(근거)만 만든다** — AI는 질문 정리·초안 문장만. 근거 줄 번호 없는 문장, 근거에 없는 숫자·날짜·판단 표현은 엔진이 자동으로 뺍니다.
2. **출처를 바꾸기 전에 겹치는 날 1:1 대조** — 예: 수급을 KIS로 채우기 전 8곳×5일 40/40 대조, 외국인 한도 종목은 「소진율 ≠ 보유율」이라 보유율만 비움.
3. **투자 권유 표현 없음**, 주문 기능 없음(조회만).
4. **키는 각자 PC의 키 파일(`local-env.cmd`)·서버 환경 변수에만.** 저장소·채팅·화면에 남기지 않습니다.

## 내 PC에서 돌려 보기 (요약)
1. Python 3.12, `engine/setup.cmd` → `engine/local-env.example.cmd`를 `local-env.cmd`로 복사해 **본인 키**(DART, KIS 조회용, 선택: Claude)를 넣기
2. 자료: Neon 사본은 `tools/neon_snapshot`(읽기 전용 접속은 `docs/DB_READONLY.md`), 이후 `tools/price_refresh`·`tools/flow_refresh`로 본인 KIS 키를 써서 최신화
3. `engine/start.cmd` → 브라우저 `http://127.0.0.1:4395`
자세한 따라하기 안내서(1~6단계: 설치·키·나만의 Neon·갱신·백업·AWS)는 이어서 올립니다.

## 문의
SW(PM). DB 관련 변경은 `docs/DATA_CHANGES.md` 규칙을 따릅니다.
