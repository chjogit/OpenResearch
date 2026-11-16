# v0.39.2 연구용 데이터 — KIS 현재가 보여 주기 · 컨센서스(연구용) (PM 결정 2026-11-15)

PM 결정: 「연구용이라 구현 자체는 가능하게. 구현이 확인되면 별도 계약」. 컨센서스 데이터는 「보고서 집계 + 정식 파일 틀」(포털 자동 수집은 하지 않음 — 이용약관).

| 번호 | 내용 | 파일 | 스위치 | 기존 API·숫자 영향 |
|---|---|---|---|---|
| 1 | GET /api/quote/{ticker}: 한국투자증권 현재가·전일 대비 %, 30초 캐시, KIS 사용량 기존 kis_usage에 셈. 「연구용(재배포 계약 전)」 표시 | mrn/research_data.py · research_data_api.py | MODU_SHOW_QUOTES=1 일 때만(기본 꺼짐 — 꺼져 있으면 KIS를 부르지 않음) | 없음(새 API). X2 유지: 답 카드·근거 확인서에 시세 안 넣음 |
| 2 | GET /api/consensus/{ticker}?cutoff=: ① 승인된 증권사 보고서 집계(연도·항목별 최신 중앙값·범위·보고서 수, 기존 N16 계산 그대로) ② 정식 데이터 파일 `_sources/consensus/*.csv`(형식 `provider,ticker,fiscal_year,metric,value_mn,n_estimates,as_of`, 틀린 줄은 이유와 함께 뺌, 제공처·연도·항목별 최신 1줄, 기준 날짜 뒤 줄 제외) | 같음 | MODU_SHOW_CONSENSUS=0 이면 끔(기본 켬) · 폴더 MODU_NODES_CONSENSUS_DIR | 없음(새 API) |
| 3 | GET /api/research/flags: 두 스위치 상태 | research_data_api.py | — | 없음 |

- server.py 는 등록 두 줄만(patch_research_data.py). 시험 8개(tests/test_v0392_research_data.py) · 전체 589개 통과(건너뜀 1) · 되짚기(verify_rebuild.py).
- 계약 뒤: 받은 파일을 위 형식 csv로 `_sources/consensus/` 에 넣으면 바로 「정식 데이터」 칸에 나옴. 시세는 계약 범위에 맞춰 MODU_SHOW_QUOTES 를 켬.
