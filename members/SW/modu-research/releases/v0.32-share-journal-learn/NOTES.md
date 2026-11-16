# v0.32-share-journal-learn — T1 공유용 페이지 · T2 가설 일지 · T3 배우는 길
기준: v0.31-transparency-label 위. 근거 문서: claude.ai 문서 「모두의리서치 · 기업분석 — 유저별 「얻음」과 만족·아쉬움 분석」의 우선순위 T1~T3.

## T1 공유용 페이지 (mrn/share.py, share_api.py)
- GET /api/share/{rid}?q= → 한 장짜리 HTML 내려받기. 같은 실행의 easy.answer + easy.receipt만 씀(새 숫자 없음).
- CSP default-src 'none'(외부 요청 없음), 링크는 http(s)만, 모든 글자 이스케이프. 확인서 JSON을 <script type="application/json" id="modu-receipt">로 내장.
- 쉬운 화면: 답 아래 「공유용 페이지 내려받기」. 「확인서로 다시 계산해 보기」가 .html도 받음(내장 확인서를 꺼내 기존 verify로).
- 감사 기록 easy.share(확인 번호 앞 8자만).
## T2 가설 일지 (mrn/journal.py, journal_api.py)
- GET /api/journal: 내 crowd_assumptions 기록 → 주제(회사·연도·항목)별 묶음. 그때 증권사 = 적은 날까지 승인 전망 집계(forecasts.as_of), 그때 모두 = 적은 시각까지 5명 이상일 때만, 실제 = 공시 API 연간 재무(사업보고서).
- 채점: 공시일 전에 적은 것만(당일·뒤 = after). 오차 = 내 가정 ÷ 실제 − 1, 증권사 오차와 크기 비교(±0.05%p 안은 비슷).
- POST /api/journal/note: 300자 메모(나만 봄), 새 표 hypothesis_notes. 감사 기록엔 글자 수만.
## T3 배우는 길 (mrn/learn.py)
- 과제 9개 · 3단계(읽기/따져 보기/증명하기). 진도는 실행·가정·메모·확인서 검증·공유 기록에서 서버가 알아냄. 화면 안에서만 하는 일(evidence·strip·then)만 POST /api/learn/mark. 새 표 learn_marks.
- 위쪽 「가설 일지」「배우는 길 n/9」 버튼, 두 화면(view) 추가.
## 공용 파일 변경 최소화
- server.py: 끝에 register 두 줄 묶음. easy.js: 끝에 덧붙임(openAnswer·verifyFile·openAbout·renderForecast를 감싸는 방식, 원래 함수 본문은 그대로). easy.html: 버튼 2개·화면 2개·파일 받는 형식(.html 추가).
## 검증
- 장치 앱 폴더 전체 시험 295개 통과(신규 6), 2차_실제 기준선 898 일치.
- 클라우드에서 실제 서버(시험용 사본)로 화면 확인: 공유 버튼 → .html 내려받기 → 새 탭에서 열림 → 그 파일로 다시 계산 2/2 일치, 가설 일지 채점(−8.3%)·메모, 배우는 길 진도, 콘솔 오류 0.
