# Agent 가 쓰는 Neon 테이블·뷰

정의 원본은 kic-agent-data 의 [`sql/`](https://github.com/chjogit/kic-agent-data/tree/main/sql) 입니다. 스키마가 바뀌면 그쪽이 기준입니다. 바뀐 내역은 [`DATA_CHANGES.md`](DATA_CHANGES.md)(두 저장소 공통)에 날짜순으로 있습니다. 최종 갱신 2026-11-03.

## DB 배치·보관

| 위치 | 담는 것 | 접속 |
|---|---|---|
| 메인 (Neon) | 종목·시세·재무·공시·거시·수급·지표, 뉴스(`naver_news`·`finnhub_news`·`naver_news_backfill`)·유튜브 댓글·사업보고서 섹션(`dart_report`) 문서, RAG 청크, 작업 상태(`ops.*`) | `DATABASE_URL` (읽기 전용 `agent_reader`) |
| kic-opinion (Neon 별도 프로젝트) | 블로그·카페(`naver_blog`·`naver_cafe`) 문서, 감성 점수, 일별 집계. 메인에는 블로그·카페가 없음 | `OPINION_DATABASE_URL` (읽기 전용 계정 별도 필요) |
| Object Storage (Neon) | DART 정기(A)·주요사항(B) 공시 원문 zip. 메타는 메인 `ops.dart_archive` | 에이전트 읽기 접속 없음 |

보관 기한: 뉴스(`naver_news`·`finnhub_news`)·유튜브 댓글·블로그·카페는 **발행일 기준 14일**, 지운 문서는 `core.doc_daily_agg` 에 일별 집계로 남음(감성·청크도 함께 삭제). `naver_news_backfill`·`dart_report`·`core.youtube_video` 는 삭제 안 함. `doc_id` 는 kic-opinion 이 메인 최대값 + 10억부터라 겹치지 않음.

## 표

| 용도 | 테이블·뷰 | 주요 열 | 쓰는 도구 |
|---|---|---|---|
| 종목 마스터 | `core.company` | market, ticker, name, sector, sector_desc, corp_code, shares_outstanding | 전체 |
| TTM 실적·멀티플 | `core.v_ttm` | ttm_end, revenue_ttm, operating_income_ttm, net_income_ttm, equity, per_ttm, pbr, op_margin_ttm, roe_ttm, debt_ratio | core_finance_peer_analyst |
| 분기 단독값 | `core.financial_quarter` | company_id, period_end, metric, amount | core_finance_peer_analyst |
| 연간 밸류에이션 | `core.v_valuation` | fiscal_year, per, pbr, op_margin, roe, debt_ratio | core_finance_peer_analyst |
| Peer 그룹 | `core.peer_group`, `core.peer_member` | base_company_id, method / rank, reason | core_finance_peer_analyst |
| 일별 시세 | `core.price_daily` | trade_date, close, volume, market_cap | core_finance_peer_analyst |
| 5개 관점 지표 | `core.feature_snapshot` | as_of, perspective, feature, value, unit | 전체 |
| 공시 목록 | `core.disclosure` | rcept_no, rcept_dt, report_nm | dart_sec_risk_examiner |
| 재무제표 원계정 | `core.financial_fact` | fiscal_year, report_code, sj_div, account_nm, amount | dart_sec_risk_examiner |
| 문서·청크 | `rag.document`, `rag.chunk` | document: source, title, summary, published_at(14일 보관) / chunk: content, embedding(**halfvec 1024**, Upstage solar-embedding-2) | dart_sec_risk_examiner |
| 문서 일별 집계 | `core.doc_daily_agg` (메인·kic-opinion 각각) | company_id, source, d, n_docs, n_scored, score_sum (평균 = score_sum / n_scored) | 14일 넘은 감성·문서 수 |
| 공시 원문 보관 메타 | `ops.dart_archive`, `ops.dart_archive_skip` | rcept_no, category(A/B), object_key, size_bytes | 에이전트는 읽지 않음(참고) |
| 거시 | `core.macro_series`, `core.macro_obs` | series_id, obs_date, value | macro_sentiment_tracker |
| 감성·언급량 | `core.reaction_pulse`, `core.mention_count`, `core.doc_sentiment` (블로그·카페 감성은 kic-opinion 쪽) | sentiment, mentions_vs_30d, total | macro_sentiment_tracker |
| 수급 | `core.investor_flow_daily`, `core.stock_lending_daily` | 외국인·기관 순매수, 대차잔고 | macro_sentiment_tracker |
