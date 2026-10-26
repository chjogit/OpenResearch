# Agent 가 쓰는 Neon 테이블·뷰

정의 원본은 kic-agent-data 의 [`sql/`](https://github.com/chjogit/kic-agent-data/tree/main/sql) 입니다. 스키마가 바뀌면 그쪽이 기준입니다.

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
| 문서·청크 | `rag.document`, `rag.chunk` | content, embedding(vector 1024) | dart_sec_risk_examiner |
| 거시 | `core.macro_series`, `core.macro_obs` | series_id, obs_date, value | macro_sentiment_tracker |
| 감성·언급량 | `core.reaction_pulse`, `core.mention_count`, `core.doc_sentiment` | sentiment, mentions_vs_30d, total | macro_sentiment_tracker |
| 수급 | `core.investor_flow_daily`, `core.stock_lending_daily` | 외국인·기관 순매수, 대차잔고 | macro_sentiment_tracker |
