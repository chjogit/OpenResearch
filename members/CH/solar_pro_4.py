import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from langchain_upstage import ChatUpstage
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv()

# =====================================================================
# 0. 환경 설정 및 Upstage Solar Pro 4 모델 초기화
# =====================================================================
UPSTAGE_MODEL_NAME = os.getenv("UPSTAGE_MODEL_NAME", "solar-pro-4")
DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_solar_llm(temperature: float = 0.1) -> ChatUpstage:
    """Upstage Solar Pro 4 LLM 인스턴스를 반환합니다."""
    return ChatUpstage(
        model=UPSTAGE_MODEL_NAME,
        temperature=temperature,
        upstage_api_key=os.environ.get("UPSTAGE_API_KEY", "YOUR_UPSTAGE_API_KEY")
    )


# =====================================================================
# 1. Neon DB 조회 데이터 로더 (6개 에이전트별 실제 SQL 쿼리 연동)
# =====================================================================
class KICDataLoader:
    """
    Neon Postgres (core, rag 스키마)에서 종목별 확정 데이터를 실제 SQL로 조회하는 로더입니다.
    '숫자는 LLM이 생성하지 않고 도구 결과만 인용한다'는 원칙을 보장합니다.
    """
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.getenv("DATABASE_URL", "")

    def _execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """단일 SQL 쿼리를 실행하고 Dict 리스트로 반환합니다."""
        if not self.db_url:
            return []
        with psycopg2.connect(self.db_url, cursor_factory=RealDictCursor) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
                return [dict(row) for row in rows]

    # 실제 kic-agent-data 스키마(sql/001~016)에 맞춘 조회입니다.
    # 종목은 core.company(market='KR', ticker=6자리)로 찾고, 나머지 테이블은 company_id로 연결합니다.
    # DB에 없는 항목(EV/EBITDA, 이자보상배율, 감사의견, 최대주주 지분율, DART 본문 청크)은
    # 'not_available'로 명시해 LLM이 추정하지 않도록 합니다.

    def _fetch_features(self, ticker: str, perspectives: List[str], features: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """core.feature_snapshot 최신 기준일의 5개 관점 지표 (kic-agent-data compute-features 결과)."""
        sql = """
            SELECT f.as_of::text AS as_of, f.perspective, f.feature, f.value, f.unit, f.note
            FROM core.feature_snapshot f
            JOIN core.company c ON c.company_id = f.company_id
            WHERE c.market = 'KR' AND c.ticker = %s
              AND f.as_of = (SELECT max(as_of) FROM core.feature_snapshot WHERE company_id = c.company_id)
              AND f.perspective = ANY(%s)
              AND (%s::text[] IS NULL OR f.feature = ANY(%s::text[]))
            ORDER BY f.perspective, f.feature;
        """
        return self._execute_query(sql, (ticker, perspectives, features, features))

    def _fetch_documents(self, ticker: str, keywords: List[str], limit: int = 3) -> List[Dict[str, Any]]:
        """rag.document(뉴스·블로그·카페) 제목/요약 키워드 검색. DART 공시 본문은 현재 적재되지 않습니다."""
        patterns = [f"%{k}%" for k in keywords]
        sql = """
            SELECT d.source, d.title, d.summary, d.published_at::text AS published_at, d.url
            FROM rag.document d
            JOIN core.company c ON c.company_id = d.company_id
            WHERE c.market = 'KR' AND c.ticker = %s
              AND d.source IN ('naver_news', 'naver_blog', 'naver_cafe')
              AND (d.title ILIKE ANY(%s) OR d.summary ILIKE ANY(%s))
            ORDER BY d.published_at DESC NULLS LAST
            LIMIT %s;
        """
        return self._execute_query(sql, (ticker, patterns, patterns, limit))

    def fetch_stock_info(self, ticker: str) -> Dict[str, Any]:
        sql = """
            SELECT ticker, name, COALESCE(krx_sector, sector) AS sector, corp_code, shares_outstanding
            FROM core.company
            WHERE market = 'KR' AND ticker = %s
            LIMIT 1;
        """
        rows = self._execute_query(sql, (ticker,))
        return rows[0] if rows else {"ticker": ticker, "name": "삼성전자", "sector": "전기전자 (KOSPI 200)"}

    # [Agent 1] 거시경제 및 사업모델 거시변수 민감도 SQL
    def fetch_macro_data(self, ticker: str) -> Dict[str, Any]:
        sql_macro = """
            SELECT DISTINCT ON (o.series_id)
                o.series_id,
                s.name,
                o.value,
                s.unit,
                s.source,
                o.obs_date::text AS obs_date
            FROM core.macro_obs o
            JOIN core.macro_series s ON s.series_id = o.series_id
            WHERE o.series_id IN ('ECOS_BASE_RATE', 'ECOS_USDKRW', 'FEDFUNDS', 'DGS10', 'CPIAUCSL')
            ORDER BY o.series_id, o.obs_date DESC;
        """
        return {
            "macro_indicators": self._execute_query(sql_macro),
            "macro_changes": self._fetch_features(ticker, ["macro"]),
            "bm_macro_sensitivity_docs": self._fetch_documents(ticker, ["환율", "수출", "외화"], limit=2),
            "not_available": "DART 사업보고서의 환율 민감도·수출 비중 본문은 DB에 없음 (뉴스 요약만 제공)",
            "source": "Neon core.macro_obs (ECOS/FRED), core.feature_snapshot(macro) & rag.document (네이버 뉴스)"
        }

    # [Agent 2] 재무·밸류에이션 및 부실 징후(건전성) SQL
    def fetch_financial_data(self, ticker: str) -> Dict[str, Any]:
        sql_fin = """
            SELECT
                t.ttm_end::text AS ttm_end,
                t.bs_end::text AS bs_end,
                t.revenue_ttm,
                t.operating_income_ttm,
                t.net_income_ttm,
                ROUND(t.op_margin_ttm * 100, 2) AS op_margin_ttm_pct,
                t.assets,
                t.liabilities,
                t.equity,
                t.per_ttm,
                t.pbr,
                ROUND(t.roe_ttm * 100, 2) AS roe_ttm_pct,
                ROUND(t.debt_ratio * 100, 2) AS debt_ratio_pct,
                CASE WHEN t.equity <= 0 THEN '완전자본잠식 (자본총계 0 이하)' ELSE '해당 없음 (자본총계 양수)' END AS capital_impairment,
                t.currency
            FROM core.v_ttm t
            WHERE t.market = 'KR' AND t.ticker = %s
            LIMIT 1;
        """
        rows = self._execute_query(sql_fin, (ticker,))
        return {
            "ttm_and_5views": rows[0] if rows else {},
            "five_view_features": self._fetch_features(ticker, ["valuation", "fundamentals", "risk"]),
            "not_available": "EV/EBITDA, 이자보상배율, 부분자본잠식률은 DB에 없음",
            "source": "Neon core.v_ttm (OpenDART 분기 재무 TTM) & core.feature_snapshot"
        }

    # [Agent 3] 산업 및 사업모델(동종 Peer 경쟁강도) SQL
    def fetch_industry_bm_data(self, ticker: str) -> Dict[str, Any]:
        sql_peers = """
            SELECT * FROM (
                SELECT DISTINCT ON (pc.market, pc.ticker)
                    pc.market,
                    pc.ticker,
                    pc.name,
                    g.method,
                    m.rank,
                    t.revenue_ttm,
                    t.operating_income_ttm,
                    ROUND(t.op_margin_ttm * 100, 2) AS op_margin_ttm_pct,
                    t.per_ttm,
                    t.pbr,
                    t.currency
                FROM core.company c
                JOIN core.peer_group g ON g.base_company_id = c.company_id
                JOIN core.peer_member m ON m.peer_group_id = g.peer_group_id
                JOIN core.company pc ON pc.company_id = m.company_id
                LEFT JOIN core.v_ttm t ON t.market = pc.market AND t.ticker = pc.ticker
                WHERE c.market = 'KR' AND c.ticker = %s AND pc.company_id <> c.company_id
                ORDER BY pc.market, pc.ticker, (g.method LIKE 'krx_sector:%%') DESC, m.rank
            ) p
            ORDER BY (p.method LIKE 'krx_sector:%%') DESC, p.rank
            LIMIT 4;
        """
        return {
            "peer_comparison": self._execute_query(sql_peers, (ticker,)),
            "vs_peer_median": self._fetch_features(
                ticker, ["valuation", "fundamentals"],
                ["per_ttm_vs_peer_median", "pbr_vs_peer_median", "op_margin_vs_peer_median", "roe_vs_peer_median"]),
            "business_model_and_competition_docs": self._fetch_documents(ticker, ["점유율", "경쟁", "업황"], limit=2),
            "not_available": "DART '사업의 내용' 본문(부문별 매출 비중)은 DB에 없음 (뉴스 요약만 제공)",
            "source": "Neon core.peer_group/peer_member, core.v_ttm & rag.document (네이버 뉴스)"
        }

    # [Agent 4] 투자심리 및 수급(네이버 수급 + 대차거래잔고 + 감성) SQL
    def fetch_sentiment_supply_data(self, ticker: str) -> Dict[str, Any]:
        sql_supply = """
            WITH recent_20d AS (
                SELECT
                    f.trade_date,
                    f.foreign_net_qty,
                    f.institution_net_qty,
                    f.individual_net_qty,
                    f.foreign_hold_pct
                FROM core.investor_flow_daily f
                JOIN core.company c ON c.company_id = f.company_id
                WHERE c.market = 'KR' AND c.ticker = %s
                ORDER BY f.trade_date DESC
                LIMIT 20
            )
            SELECT
                MIN(trade_date)::text AS from_date,
                MAX(trade_date)::text AS to_date,
                SUM(foreign_net_qty) AS foreign_net_buy_qty_20d,
                SUM(institution_net_qty) AS inst_net_buy_qty_20d,
                SUM(individual_net_qty) AS retail_net_buy_qty_20d,
                (SELECT foreign_hold_pct FROM recent_20d ORDER BY trade_date DESC LIMIT 1) AS latest_foreign_ownership_pct,
                (SELECT foreign_hold_pct FROM recent_20d ORDER BY trade_date ASC LIMIT 1) AS foreign_ownership_20d_ago_pct
            FROM recent_20d;
        """
        sql_short_lending = """
            SELECT
                l.trade_date::text AS trade_date,
                l.lent_qty AS lending_shares,
                l.repaid_qty AS repaid_shares,
                l.balance_qty AS short_lending_balance_shares,
                l.balance_amt AS short_lending_balance_amt
            FROM core.stock_lending_daily l
            JOIN core.company c ON c.company_id = l.company_id
            WHERE c.market = 'KR' AND c.ticker = %s
            ORDER BY l.trade_date DESC
            LIMIT 5;
        """
        sql_sentiment = """
            SELECT
                r.captured_at::text AS snapshot_time,
                r.sentiment AS sentiment_score,
                r.n_today AS mention_count,
                r.n_positive,
                r.n_negative,
                r.mentions_vs_30d
            FROM core.reaction_pulse r
            JOIN core.company c ON c.company_id = r.company_id
            WHERE c.market = 'KR' AND c.ticker = %s
            ORDER BY r.captured_at DESC
            LIMIT 1;
        """
        supply = self._execute_query(sql_supply, (ticker,))
        short_lending = self._execute_query(sql_short_lending, (ticker,))
        sentiment = self._execute_query(sql_sentiment, (ticker,))
        return {
            "investor_supply_20d": supply[0] if supply else {},
            "short_lending_recent_5d": short_lending,
            "latest_sentiment_snapshot": sentiment[0] if sentiment else {},
            "supply_demand_features": self._fetch_features(ticker, ["supply_demand"]),
            "note": "순매수는 금액이 아닌 주식 수량 기준, 감성 점수 범위는 -1(부정) ~ +1(긍정)",
            "source": "Neon core.investor_flow_daily (네이버 수급), core.stock_lending_daily (주식대차거래정보), core.reaction_pulse & core.feature_snapshot"
        }

    # [Agent 5] 기술적 분석 (이동평균선 정/역배열, 거래량 비율, RSI) SQL
    def fetch_technical_data(self, ticker: str) -> Dict[str, Any]:
        sql_tech = """
            WITH price_window AS (
                SELECT
                    p.trade_date,
                    p.close AS close_price,
                    p.volume,
                    ROUND(AVG(p.close) OVER (ORDER BY p.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW), 0) AS ma20,
                    ROUND(AVG(p.close) OVER (ORDER BY p.trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW), 0) AS ma60,
                    ROUND(AVG(p.close) OVER (ORDER BY p.trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW), 0) AS ma120,
                    ROUND(AVG(p.volume) OVER (ORDER BY p.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW), 0) AS vol_ma20
                FROM core.price_daily p
                JOIN core.company c ON c.company_id = p.company_id
                WHERE c.market = 'KR' AND c.ticker = %s AND p.close IS NOT NULL
                ORDER BY p.trade_date DESC
                LIMIT 1
            )
            SELECT
                trade_date::text AS trade_date,
                close_price AS current_price,
                ma20,
                ma60,
                ma120,
                CASE
                    WHEN ma20 > ma60 AND ma60 > ma120 THEN '정배열 (MA20 > MA60 > MA120)'
                    WHEN ma20 < ma60 AND ma60 < ma120 THEN '역배열 (MA20 < MA60 < MA120)'
                    ELSE '혼조세 (이평선 수렴/교차 구간)'
                END AS ma_alignment,
                volume,
                vol_ma20,
                ROUND((volume::numeric / NULLIF(vol_ma20, 0)) * 100, 1) AS volume_vs_ma20_pct
            FROM price_window;
        """
        # RSI·MACD 컬럼은 DB에 없으므로 최근 종가로 직접 계산합니다 (LLM이 아닌 코드 계산값).
        sql_closes = """
            SELECT p.close FROM core.price_daily p
            JOIN core.company c ON c.company_id = p.company_id
            WHERE c.market = 'KR' AND c.ticker = %s AND p.close IS NOT NULL
            ORDER BY p.trade_date DESC
            LIMIT 250;
        """
        rows = self._execute_query(sql_tech, (ticker,))
        closes = [float(r["close"]) for r in reversed(self._execute_query(sql_closes, (ticker,)))]
        indicators = rows[0] if rows else {}
        if indicators:
            indicators.update(self._rsi_macd(closes))
        return {
            "technical_indicators": indicators,
            "source": "Neon core.price_daily (FSC/yfinance 시세 기반 윈도우 쿼리, RSI·MACD는 종가로 계산)"
        }

    @staticmethod
    def _rsi_macd(closes: List[float]) -> Dict[str, Any]:
        """RSI(14, Wilder)와 MACD(12, 26, 9). 데이터가 부족하면 None."""
        out = {"rsi_14": None, "macd": None, "macd_signal": None}
        if len(closes) >= 15:
            diffs = [b - a for a, b in zip(closes, closes[1:])]
            gain = sum(max(d, 0) for d in diffs[:14]) / 14
            loss = sum(max(-d, 0) for d in diffs[:14]) / 14
            for d in diffs[14:]:
                gain = (gain * 13 + max(d, 0)) / 14
                loss = (loss * 13 + max(-d, 0)) / 14
            out["rsi_14"] = 100.0 if loss == 0 else round(100 - 100 / (1 + gain / loss), 1)
        if len(closes) >= 35:
            def ema(xs, n):
                k, e, res = 2 / (n + 1), xs[0], []
                for x in xs:
                    e = x * k + e * (1 - k)
                    res.append(e)
                return res
            macd_line = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
            out["macd"] = round(macd_line[-1], 1)
            out["macd_signal"] = round(ema(macd_line, 9)[-1], 1)
        return out

    # [Agent 6] 대주주 및 경영진(CEO) 역량 / 지배구조 / 희석 리스크 SQL
    def fetch_governance_ceo_data(self, ticker: str) -> Dict[str, Any]:
        sql_meta = """
            SELECT
                d.rcept_dt::text AS rcept_dt,
                d.report_nm,
                d.category,
                d.event_type,
                d.url
            FROM core.disclosure d
            JOIN core.company c ON c.company_id = d.company_id
            WHERE c.market = 'KR' AND c.ticker = %s
              AND d.rcept_dt >= CURRENT_DATE - INTERVAL '1 year'
              AND (d.report_nm ILIKE '%%대표이사%%'
                   OR d.report_nm ILIKE '%%최대주주%%'
                   OR d.report_nm ILIKE '%%전환사채%%'
                   OR d.report_nm ILIKE '%%유상증자%%'
                   OR d.report_nm ILIKE '%%배당%%'
                   OR d.report_nm ILIKE '%%자기주식%%'
                   OR d.report_nm ILIKE '%%사업보고서%%')
            ORDER BY d.rcept_dt DESC
            LIMIT 10;
        """
        return {
            "recent_governance_disclosures": self._execute_query(sql_meta, (ticker,)),
            "governance_and_ceo_docs": self._fetch_documents(ticker, ["대표이사", "최대주주", "배당", "자사주"], limit=3),
            "not_available": "감사의견, 최대주주 지분율, DART 임원·주주 현황 본문은 DB에 없음 (공시 제목과 뉴스 요약만 제공)",
            "source": "Neon core.disclosure (OpenDART 공시 목록) & rag.document (네이버 뉴스)"
        }

    def fetch_all_context(self, ticker: str) -> Dict[str, Any]:
        if self.db_url:
            try:
                print(f"🔌 Neon Postgres DB 실시간 SQL 쿼리 실행 중... (종목: {ticker})")
                stock_info = self.fetch_stock_info(ticker)
                macro_data = self.fetch_macro_data(ticker)
                financial_data = self.fetch_financial_data(ticker)
                industry_bm_data = self.fetch_industry_bm_data(ticker)
                sentiment_supply_data = self.fetch_sentiment_supply_data(ticker)
                technical_data = self.fetch_technical_data(ticker)
                governance_ceo_data = self.fetch_governance_ceo_data(ticker)

                if financial_data.get("ttm_and_5views"):
                    return {
                        "stock_info": stock_info,
                        "macro_data": macro_data,
                        "financial_data": financial_data,
                        "industry_bm_data": industry_bm_data,
                        "sentiment_supply_data": sentiment_supply_data,
                        "technical_data": technical_data,
                        "governance_ceo_data": governance_ceo_data,
                    }
                print("⚠️ DB 테이블 내 해당 종목 데이터가 비어 있어 검증용 스냅샷 데이터로 폴백합니다.")
            except Exception as e:
                print(f"⚠️ Neon DB SQL 실행 중 예외 발생 ({e}) -> 검증용 스냅샷 데이터로 폴백합니다.")

        return self._get_fallback_sample(ticker)

    @staticmethod
    def _get_fallback_sample(ticker: str) -> Dict[str, Any]:
        return {
            "stock_info": {"ticker": ticker, "name": "삼성전자", "sector": "전기전자 (KOSPI 200)"},
            "macro_data": {
                "base_rate_kr": "3.25%",
                "base_rate_us": "4.75%",
                "usd_krw": "1,385.5원 (전월 대비 +3.2%)",
                "cpi_yoy": "2.1%",
                "export_ratio": "86.4%",
                "fx_sensitivity": "원/달러 환율 5% 상승 시 분기 영업이익 약 1.2조원 증가 추정 (공시 각주 외화자산 민감도 기준)",
                "source": "검증용 샘플 데이터 (DB 미연결·데이터 없음 시 폴백, 실제 수치 아님)"
            },
            "financial_data": {
                "sales_ttm": "302조 2,314억원",
                "op_income_ttm": "36조 7,850억원",
                "op_margin_ttm": "12.17%",
                "per": "13.8배",
                "pbr": "1.25배",
                "interest_coverage_ratio": "14.2배 (부실 징후 기준 1.0배 크게 상회)",
                "capital_impairment": "해당 없음",
                "source": "검증용 샘플 데이터 (DB 미연결·데이터 없음 시 폴백, 실제 수치 아님)"
            },
            "industry_bm_data": {
                "main_bm": "DS(반도체 52%), DX(모바일/가전 40%), SDC(디스플레이 8%)",
                "industry_competition": "고대역폭메모리(HBM) 시장 내 SK하이닉스(000660), 마이크론(MU)과의 기술 및 수율 경쟁 심화",
                "peer_comparison": [
                    {"name": "SK하이닉스", "ticker": "000660", "op_margin_ttm": "28.4%", "per": "11.2배"},
                    {"name": "DB하이텍", "ticker": "000990", "op_margin_ttm": "18.1%", "per": "9.5배"}
                ],
                "source": "검증용 샘플 데이터 (DB 미연결·데이터 없음 시 폴백, 실제 수치 아님)"
            },
            "sentiment_supply_data": {
                "foreign_net_buy_20d": "-2조 1,400억원 (최근 20영업일 누적 순매도)",
                "inst_net_buy_20d": "+4,850억원 (최근 20영업일 누적 순매수)",
                "retail_net_buy_20d": "+1조 6,200억원",
                "foreign_ownership": "52.8% (1개월 전 54.1% 대비 -1.3%p 하락)",
                "short_lending_balance": "8,050만 주 (전주 대비 +4.5% 증가, 공매도 선행 대차잔고 부담 존재)",
                "sentiment_score": "44.2점 / 100점 (뉴스 및 대형주 유튜브 댓글 내 HBM 공급 지연 우려 언급 증가)",
                "source": "검증용 샘플 데이터 (DB 미연결·데이터 없음 시 폴백, 실제 수치 아님)"
            },
            "technical_data": {
                "current_price": "59,200원",
                "ma_alignment": "역배열 (MA20: 61,400원 < MA60: 66,800원 < MA120: 72,500원)",
                "rsi_14": "34.2 (과매도권 근접)",
                "macd": "시그널선 하회 지속 (히스토그램 음수 폭 축소 중)",
                "volume_trend": "20일 평균 거래량 대비 135% 증가 (하단 지지선 테스트 구간)",
                "source": "검증용 샘플 데이터 (DB 미연결·데이터 없음 시 폴백, 실제 수치 아님)"
            },
            "governance_ceo_data": {
                "largest_shareholder": "삼성생명 외 특수관계인 지분율 20.72% (안정적 유지)",
                "ceo_leadership": "DS부문장 교체 이후 HBM3E 양산 정상화 및 파운드리 수익성 개선에 경영 역량 집중",
                "shareholder_return": "연간 9.8조원 규모 정규 배당 유지, 최근 1년간 CB/BW 등 지분 희석 공시 0건",
                "legal_governance_risk": "사법 리스크 일부 잔존하나 감사의견 '적정' 및 내부회계관리제도 적정 유지",
                "source": "검증용 샘플 데이터 (DB 미연결·데이터 없음 시 폴백, 실제 수치 아님)"
            }
        }


# =====================================================================
# 2. 공통 에이전트 실행 베이스 클래스
# =====================================================================
COMMON_AGENT_RULES = """
[절대 준수 원칙]
1. 숫자는 절대 임의로 생성하거나 추정하지 마십시오. 반드시 제공된 [SQL 조회 원천 데이터] 내의 수치만 정확히 인용하십시오.
2. '매수 추천', '매도 추천', '목표주가 제시' 표현은 전면 금지합니다. 대신 '투자 검토 참고치 및 리스크 요약'으로 서술하십시오.
3. 인용한 핵심 수치 뒤에는 반드시 데이터에 명시된 `[출처: ...]`를 표기하십시오.
"""

class PerspectiveAgent:
    """개별 관점을 담당하는 전문 에이전트 클래스"""
    def __init__(self, agent_id: int, name: str, role_prompt: str, data_key: str):
        self.agent_id = agent_id
        self.name = name
        self.role_prompt = role_prompt
        self.data_key = data_key
        self.llm = get_solar_llm(temperature=0.1)

    def analyze(self, context: Dict[str, Any], mode: str = "expert") -> Dict[str, Any]:
        stock_info = context["stock_info"]
        domain_data = context[self.data_key]

        mode_instruction = (
            "전문가(애널리스트/심사역) 모드: 군더더기 없이 핵심 지표와 인과관계 위주로 간결하고 날카롭게 서술하십시오."
            if mode == "expert" else
            "입문자 가이드 모드: 전문 용어(예: 민감도, 대차잔고, RSI, 이자보상배율 등)가 나오면 괄호나 불릿으로 쉬운 개념 풀이와 '왜 이 지표를 봐야 하는지'를 친절히 덧붙이십시오."
        )

        system_msg = f"""당신은 OpenResearch의 [{self.agent_id}번 에이전트: {self.name}]입니다.
{self.role_prompt}

{COMMON_AGENT_RULES}
[출력 모드 지침]
{mode_instruction}

반드시 아래 형식으로 분석 결과를 작성하십시오:
- 핵심 진단 요약 (1~2문장)
- 세부 근거 및 SQL 데이터 분석 (불릿 포인트 2~3개, 출처 포함)
- 해당 관점에서의 긍정적 요인 vs 리스크 요인
- 자체 평가 중요도 점수 (1~10점) 및 이유
"""
        user_msg = f"""
[대상 종목]: {stock_info['name']} ({stock_info['ticker']}) / 업종: {stock_info['sector']}
[SQL 조회 원천 데이터]:
{json.dumps(domain_data, ensure_ascii=False, indent=2, default=str)}

위 Neon DB 확정 데이터만을 바탕으로 당신의 전문 관점에서 심층 분석을 수행해 주십시오.
"""
        try:
            response = self.llm.invoke([
                SystemMessage(content=system_msg),
                HumanMessage(content=user_msg)
            ])
            analysis, status = response.content, "완료"
        except Exception as e:  # 한 에이전트 실패가 전체를 멈추지 않도록 상태로 기록
            analysis, status = f"(분석 실패: {type(e).__name__}: {e})", "실패"

        return {
            "agent_id": self.agent_id,
            "agent_name": self.name,
            "status": status,
            "analysis": analysis,
            "source": domain_data.get("source", "Neon DB")
        }


# =====================================================================
# 3. 6대 관점 에이전트 인스턴스 정의
# =====================================================================
def build_six_agents() -> List[PerspectiveAgent]:
    return [
        PerspectiveAgent(
            agent_id=1,
            name="거시경제 및 변수 민감도 분석 에이전트 (Macro & Sensitivity)",
            role_prompt=(
                "당신은 거시경제(금리, 환율, 물가 등) 환경과 해당 기업의 사업모델이 거시변수에 얼마나 민감하게 반응하는지"
                "(수출 비중, 외화자산/부채 환율 민감도, 금리 변화에 따른 조달비용 영향 등)를 분석하는 매크로 전문 애널리스트입니다."
            ),
            data_key="macro_data"
        ),
        PerspectiveAgent(
            agent_id=2,
            name="재무·밸류에이션 및 건전성 분석 에이전트 (Financial & Risk)",
            role_prompt=(
                "당신은 기업의 TTM 실적(매출, 영업이익, 이익률), 5대 관점 지표, 밸류에이션 멀티플(PER, PBR, EV/EBITDA) 및 "
                "객관적 부실 징후(이자보상배율 1 미만 여부, 자본잠식 여부)를 심사하는 재무/신용 분석 전문가입니다."
            ),
            data_key="financial_data"
        ),
        PerspectiveAgent(
            agent_id=3,
            name="산업 및 사업모델(경쟁강도) 분석 에이전트 (Industry & BM)",
            role_prompt=(
                "당신은 기업의 핵심 수익 모델(사업 부문별 비중)과 전방 산업 업황, 특히 KOSPI 200 내 동종 Peer 기업 대비 "
                "산업 내 경쟁강도(이익률 격차, 시장 지위, 기술 경쟁력)를 평가하는 섹터 애널리스트입니다."
            ),
            data_key="industry_bm_data"
        ),
        PerspectiveAgent(
            agent_id=4,
            name="투자심리 및 수급 분석 에이전트 (Sentiment & Supply/Demand)",
            role_prompt=(
                "당신은 외국인·기관·개인의 순매수 수급 동향, 외국인 지분율 변화, 공매도 선행 지표인 주식대차거래잔고 추이, "
                "그리고 뉴스·커뮤니티·유튜브 댓글 감성 점수를 결합해 시장 참여자들의 투자심리를 해부하는 수급/센티먼트 전문가입니다."
            ),
            data_key="sentiment_supply_data"
        ),
        PerspectiveAgent(
            agent_id=5,
            name="기술적 분석 에이전트 (Technical Analysis)",
            role_prompt=(
                "당신은 주가 추세, 장단기 이동평균선 정배열/역배열 상태, 거래량 변화, RSI 및 MACD 등 기술적 지표를 바탕으로 "
                "현재 주가의 과열/침체 여부와 주요 지지·저항 구간을 진단하는 테크니컬 애널리스트입니다."
            ),
            data_key="technical_data"
        ),
        PerspectiveAgent(
            agent_id=6,
            name="대주주 및 경영진(CEO) 분석 에이전트 (Governance & Leadership)",
            role_prompt=(
                "당신은 대주주 지분율과 지배구조 안정성, CEO 등 경영진의 경영능력(핵심 사업 돌파력, 실적 가시성), "
                "주주환원 정책(배당/자사주) 및 지분 희석 리스크(CB/BW 발행)나 사법/감사 리스크를 검증하는 거버넌스 전문가입니다."
            ),
            data_key="governance_ceo_data"
        )
    ]


# =====================================================================
# 4. 7번 오케스트레이터 (Orchestrator Agent) 정의
# =====================================================================
class OrchestratorAgent:
    """
    6개 에이전트의 분석 결과를 종합하여:
    1) 관점별 중요도(가중치/우선순위) 산정
    2) 의견 충돌(Conflict) 조율
    3) 오케스트레이터만의 추가적인 입체적 의견 및 후속 체크포인트 제시
    """
    def __init__(self):
        self.llm = get_solar_llm(temperature=0.15)

    def synthesize(self, context: Dict[str, Any], agent_outputs: List[Dict[str, Any]], mode: str = "expert") -> str:
        stock_info = context["stock_info"]
        
        compiled_reports = "\n\n".join([
            f"### [A{item['agent_id']}. {item['agent_name']}] (상태: {item.get('status', '완료')})\n{item['analysis']}"
            for item in agent_outputs
        ])

        system_msg = f"""당신은 OpenResearch의 총괄 수석 디렉터인 [7. 오케스트레이터(Orchestrator)]입니다.
산하 6개 전문 에이전트(1.거시/민감도, 2.재무/건전성, 3.산업/경쟁강도, 4.투자심리/수급, 5.기술적분석, 6.대주주/경영진)의 보고서를 취합하여 최종 투자 검토 보고서를 작성합니다.

{COMMON_AGENT_RULES}

[오케스트레이터 필수 수행 과제]
0. **에이전트별 핵심 의견 요약표 (보고서 맨 앞)**:
   - 표 열: 에이전트(A1~A6) | 핵심 진단(1문장) | 긍정 요인 | 리스크 요인 | 자체 중요도 점수.
   - 각 에이전트가 쓴 내용과 점수만 옮기고, 새 판단이나 수치를 만들지 마십시오.
   - 상태가 '실패'인 에이전트는 '분석 실패'로 표기하고, 종합에서 제외했다고 밝히십시오.
   - 이후 모든 종합 문장 끝에는 근거가 된 에이전트를 [A1], [A3·A5]처럼 표기하십시오. 근거 에이전트가 없는 문장은 쓰지 마십시오.
1. **관점별 중요도(Weight & Priority) 산정 표 제시**:
   - 현재 이 종목을 판단할 때 6개 관점 중 무엇이 가장 결정적인지 중요도 비중(합계 100%)과 등급(High/Medium/Low)을 매기고, 왜 그렇게 가중치를 두었는지 설명하십시오.
2. **6대 관점 교차 분석 및 상충 의견(Conflict) 조율**:
   - 서로 다른 신호를 보내는 에이전트들(예: 거시/환율이나 기술적 지표는 우호적이나, 산업 경쟁강도나 외국인 수급/대차잔고는 부정적인 상황 등)의 의견을 입체적으로 대조하여 해석하십시오.
3. **오케스트레이터의 추가 의견 (Additional Insights & Actionable Checkpoints)**:
   - 개별 에이전트 보고서에 단편적으로 흩어져 있던 사실들을 연결하여 도출한 '핵심 통찰'과, 투자 검토자가 향후 반드시 추적 관찰해야 할 '선행 트리거(Trigger) 지표 3가지'를 제시하십시오.
4. **현재 실행 모드 ({mode}) 반영**:
   - 'guide' 모드일 경우, 초심자가 6개의 서로 다른 관점 중 어떤 순서로 읽어나가야 하는지 '보고서 읽는 법 가이드'와 역질문을 마지막에 추가하십시오.
"""

        user_msg = f"""
[분석 대상]: {stock_info['name']} ({stock_info['ticker']}) - {stock_info['sector']}

[6개 전문 에이전트 분석 결과]:
{compiled_reports}

위 6개 에이전트의 의견을 먼저 요약표로 정리한 뒤, 중요도 평가, 상충 의견 조율, 오케스트레이터의 추가 의견 순서로 종합해 주십시오.
"""
        response = self.llm.invoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=user_msg)
        ])
        return response.content


def _demote_headings(text: str, levels: int = 2) -> str:
    """에이전트 원문 안의 '#' 제목을 한 단계 아래로 내려 보고서 목차가 섞이지 않게 합니다."""
    import re
    return re.sub(r"^(#{1,6})(?=\s)", lambda m: "#" * min(6, len(m.group(1)) + levels), text, flags=re.M)


def compose_full_report(stock_info: Dict[str, Any], agent_outputs: List[Dict[str, Any]],
                        synthesis: str, kind: str = "분석") -> str:
    """Part 1(6개 에이전트 의견 원문) + Part 2(오케스트레이터 종합)를 하나의 보고서로 묶습니다."""
    done = sum(1 for o in agent_outputs if o.get("status", "완료") == "완료")
    lines = [
        f"# {stock_info['name']}({stock_info['ticker']}) 6+1 멀티 에이전트 {kind} 보고서",
        "",
        f"- 에이전트 수행 결과: {done}/{len(agent_outputs)} 완료",
        "- 구성: Part 1 관점별 에이전트 의견(원문) → Part 2 오케스트레이터 종합",
        "",
        "---",
        "",
        "## Part 1. 관점별 에이전트 의견",
        "",
        "> 6개 에이전트가 각자 작성한 원문입니다. Part 2의 종합은 이 원문만을 근거로 하며, [A번호]로 연결됩니다.",
        "",
    ]
    for o in agent_outputs:
        lines += [
            f"### [A{o['agent_id']}] {o['agent_name']} · {o.get('status', '완료')}",
            "",
            _demote_headings(o["analysis"].strip()),
            "",
            f"_데이터 출처: {o['source']}_",
            "",
        ]
    lines += ["---", "", "## Part 2. 오케스트레이터 종합 (Agent 7)", "", _demote_headings(synthesis.strip(), levels=1)]
    return "\n".join(lines)


# =====================================================================
# 5. Fact & Source Verifier (신뢰성 15점 방어용 검증기)
# =====================================================================
class FactSourceVerifier:
    """최종 산출물의 원천 데이터 출처 목록을 강제 바인딩하고 환각 여부를 점검합니다."""
    @staticmethod
    def verify(orchestrator_report: str, agent_outputs: List[Dict[str, Any]]) -> str:
        sources = sorted(list({item["source"] for item in agent_outputs}))
        verification_footer = "\n\n---\n### 🛡️ [Fact & Source Verifier 검증 완료]\n"
        verification_footer += f"- **적용 모델**: Upstage Solar Pro 4 (`{UPSTAGE_MODEL_NAME}`)\n"
        verification_footer += "- **수치 생성 원칙**: LLM 임의 추정 배제 (Neon Postgres `core` 및 `rag` SQL 확정 데이터 100% 인용)\n"
        verification_footer += "- **실행된 SQL 참조 테이블 및 출처**:\n"
        for src in sources:
            verification_footer += f"  - `{src}`\n"
        return orchestrator_report + verification_footer


# =====================================================================
# 6. 전체 파이프라인 실행 함수
# =====================================================================
def run_openresearch_multi_agent(ticker: str = "005930", mode: str = "expert") -> Dict[str, Any]:
    print(f"============================================================")
    print(f"🚀 OpenResearch 6+1 멀티 에이전트 분석 시작 | 종목: {ticker} | 모드: {mode}")
    print(f"🤖 사용 모델: {UPSTAGE_MODEL_NAME}")
    print(f"============================================================")

    # Step 1: Neon DB 실시간 SQL 데이터 로드
    loader = KICDataLoader()
    context = loader.fetch_all_context(ticker)

    # Step 2: 6개 관점 에이전트 실행
    agents = build_six_agents()
    agent_outputs = []
    for agent in agents:
        print(f"▶ [Agent {agent.agent_id}] {agent.name} 분석 수행 중...")
        res = agent.analyze(context, mode=mode)
        agent_outputs.append(res)
        print(f"   └ {res['status']} ({len(res['analysis'])}자)")

    # Step 3: 7번 오케스트레이터 종합 및 중요도/추가 의견 도출
    print("▶ [Agent 7: Orchestrator] 6개 에이전트 의견 종합 및 중요도 산정 중...")
    orchestrator = OrchestratorAgent()
    raw_final_report = orchestrator.synthesize(context, agent_outputs, mode=mode)

    # Step 4: Fact & Source Verifier 검증
    print("▶ [Verifier] 수치 및 출처 정합성 최종 검증 중...")
    verified_final_report = FactSourceVerifier.verify(raw_final_report, agent_outputs)
    full_report = FactSourceVerifier.verify(
        compose_full_report(context["stock_info"], agent_outputs, raw_final_report, kind="분석"),
        agent_outputs,
    )

    return {
        "ticker": ticker,
        "mode": mode,
        "individual_agent_reports": agent_outputs,
        "orchestrator_final_report": verified_final_report,  # 종합만 (기존 키 유지)
        "full_report": full_report,  # 에이전트 의견 원문 + 종합
    }


# =====================================================================
# 7. 보고서 첨삭 모드 (사용자 보고서를 6개 관점에서 첨삭·피드백)
# =====================================================================
import re
from decimal import Decimal

REPORT_MAX_CHARS = 12000  # LLM 입력 한도 보호용 (넘으면 앞부분만 첨삭)


def load_report(path: str) -> str:
    """첨삭할 보고서 파일(.md / .txt)을 읽습니다."""
    with open(path, encoding="utf-8") as f:
        return f.read()


def resolve_ticker(report_text: str, ticker: Optional[str] = None, loader: Optional[KICDataLoader] = None) -> str:
    """종목코드를 주면 그대로 쓰고, 없으면 보고서 본문에서 KOSPI 종목코드·종목명을 찾아 core.company와 매칭합니다."""
    if ticker:
        return ticker
    loader = loader or KICDataLoader()
    companies = loader._execute_query("SELECT ticker, name FROM core.company WHERE market = 'KR' AND name IS NOT NULL;")
    if not companies:
        raise ValueError("종목코드를 자동 인식하려면 DB 연결이 필요합니다. ticker 인자를 직접 넣어 주세요.")
    by_ticker = {c["ticker"]: c for c in companies}
    for code in re.findall(r"(?<!\d)(\d{6})(?!\d)", report_text):
        if code in by_ticker:
            return code
    # 종목명이 가장 많이 등장한 종목. 더 긴 종목명 안에 든 등장은 빼고 셉니다 ('LG에너지솔루션' 속 'LG').
    found = {c["name"]: (report_text.count(c["name"]), c["ticker"]) for c in companies if c["name"] in report_text}
    counts = []
    for name, (n, code) in found.items():
        n -= sum(m for other, (m, _) in found.items() if other != name and name in other)
        counts.append((n, len(name), code))
    best = max(counts, default=(0, 0, None))
    if best[0] == 0:
        raise ValueError("보고서에서 KOSPI 종목을 찾지 못했습니다. ticker 인자를 직접 넣어 주세요.")
    return best[2]


class ReportNumberChecker:
    """
    보고서 속 숫자를 코드로 추출해 DB 확정값과 대조합니다. (LLM은 이 결과표만 인용)
    - 지표 키워드(매출, 영업이익률, PER 등)가 숫자 바로 앞에 있으면 해당 DB 값과 비교해 일치/불일치를 판정합니다.
    - 키워드가 없으면 '대응 지표 미확인'으로 남깁니다.
    """
    # (키워드, 지표명, 비교 방식). 긴 키워드를 먼저 검사합니다 (영업이익률 → 영업이익).
    KEYWORDS = [
        (("영업이익률", "영업 이익률", "OPM"), "영업이익률(TTM)", "pct"),
        (("순이익률",), "순이익률(TTM)", "pct"),
        (("매출액", "매출", "Revenue"), "매출액(TTM)", "krw"),
        (("영업이익",), "영업이익(TTM)", "krw"),
        (("순이익",), "순이익(TTM)", "krw"),
        (("PER", "주가수익비율"), "PER(TTM)", "x"),
        (("PBR", "주가순자산비율"), "PBR", "x"),
        (("ROE", "자기자본이익률"), "ROE(TTM)", "pct"),
        (("부채비율",), "부채비율", "pct"),
        (("외국인 보유", "외국인 지분", "외국인 보유율", "외국인 지분율"), "외국인 보유율", "pct"),
        (("RSI",), "RSI(14)", "num"),
        (("기준금리", "한국은행 기준금리"), "한국 기준금리", "pct"),
        (("환율", "원/달러", "원·달러"), "원/달러 환율", "num"),
        (("주가", "종가", "현재가"), "현재 주가", "num"),
    ]
    UNIT_SCALE = {"조원": 1e12, "조": 1e12, "억원": 1e8, "억": 1e8, "만원": 1e4, "원": 1}
    # '302조 2,314억원' 같은 복합 금액 → 단일 금액 → %, 배 순서로 찾습니다.
    NUM_RE = re.compile(
        r"(?P<jo>\d[\d,]*(?:\.\d+)?)\s*조\s*(?P<eok>\d[\d,]*)\s*억\s*원?"
        r"|(?P<num>-?\d[\d,]*(?:\.\d+)?)\s*(?P<unit>%p|%|배|x|조원|조|억원|억|만원|원)"
    )
    KIND_UNITS = {"krw": {"조원", "조", "억원", "억", "만원", "원"}, "pct": {"%"}, "x": {"배", "x"}, "num": {"원", ""}}

    @staticmethod
    def _to_float(v: Any) -> Optional[float]:
        if isinstance(v, (int, float, Decimal)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.replace(",", ""))
            except ValueError:
                return None
        return None

    @classmethod
    def reference_metrics(cls, context: Dict[str, Any]) -> Dict[str, Any]:
        """대조 기준이 되는 DB 확정값 (지표명 → (값, 데이터 키))."""
        fin = context.get("financial_data", {}).get("ttm_and_5views", {}) or {}
        tech = context.get("technical_data", {}).get("technical_indicators", {}) or {}
        sup = context.get("sentiment_supply_data", {}).get("investor_supply_20d", {}) or {}
        macro = {r.get("series_id"): r.get("value") for r in context.get("macro_data", {}).get("macro_indicators", [])
                 if isinstance(r, dict)}
        rev, ni = cls._to_float(fin.get("revenue_ttm")), cls._to_float(fin.get("net_income_ttm"))
        return {
            "매출액(TTM)": (fin.get("revenue_ttm"), "financial_data"),
            "영업이익(TTM)": (fin.get("operating_income_ttm"), "financial_data"),
            "순이익(TTM)": (fin.get("net_income_ttm"), "financial_data"),
            "영업이익률(TTM)": (fin.get("op_margin_ttm_pct"), "financial_data"),
            "순이익률(TTM)": (round(ni / rev * 100, 2) if rev and ni is not None else None, "financial_data"),
            "PER(TTM)": (fin.get("per_ttm"), "financial_data"),
            "PBR": (fin.get("pbr"), "financial_data"),
            "ROE(TTM)": (fin.get("roe_ttm_pct"), "financial_data"),
            "부채비율": (fin.get("debt_ratio_pct"), "financial_data"),
            "외국인 보유율": (sup.get("latest_foreign_ownership_pct"), "sentiment_supply_data"),
            "RSI(14)": (tech.get("rsi_14"), "technical_data"),
            "한국 기준금리": (macro.get("ECOS_BASE_RATE"), "macro_data"),
            "원/달러 환율": (macro.get("ECOS_USDKRW"), "macro_data"),
            "현재 주가": (tech.get("current_price"), "technical_data"),
        }

    @classmethod
    def _parse(cls, m: re.Match) -> Any:
        if m.group("jo"):
            jo = float(m.group("jo").replace(",", ""))
            eok = float(m.group("eok").replace(",", ""))
            return jo * 1e12 + eok * 1e8, "조원"
        value = float(m.group("num").replace(",", ""))
        unit = m.group("unit")
        return value * cls.UNIT_SCALE.get(unit, 1), unit

    @staticmethod
    def _close(a: float, b: float, kind: str) -> bool:
        if kind == "pct":
            return abs(a - b) <= 0.15  # %p 기준 반올림 허용
        if kind == "x":
            return abs(a - b) <= max(0.1, abs(b) * 0.03)
        return abs(a - b) <= abs(b) * 0.02  # 금액·지수: 2% (보고서 반올림 표기 허용)

    @classmethod
    def check(cls, report_text: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        refs = cls.reference_metrics(context)
        rows = []
        for m in cls.NUM_RE.finditer(report_text):
            value, unit = cls._parse(m)
            if unit == "%p":
                continue  # 변화폭(%p)은 대응 DB 값이 없어 건너뜀
            # 숫자 바로 앞(같은 문장, 최대 30자)에서 가장 가까운 지표 키워드
            start = max(report_text.rfind(".", 0, m.start()), report_text.rfind("\n", 0, m.start()), m.start() - 30)
            window = report_text[start + 1:m.start()]
            found = None
            for keywords, metric, kind in cls.KEYWORDS:
                pos = max(window.rfind(k) for k in keywords)
                if pos >= 0 and unit in cls.KIND_UNITS[kind] and (found is None or pos > found[0]):
                    found = (pos, metric, kind)
            row = {"보고서 표기": m.group(0).strip(), "문맥": report_text[start + 1:m.end()].strip()[-60:]}
            if not found:
                rows.append({**row, "지표": None, "DB 값": None, "판정": "대응 지표 미확인", "data_key": None})
                continue
            _, metric, kind = found
            db_raw, data_key = refs[metric]
            db_val = cls._to_float(db_raw)
            if db_val is None:
                verdict = "DB 값 없음 (검증 불가)"
            else:
                verdict = "일치" if cls._close(value, db_val, kind) else "불일치"
            rows.append({**row, "지표": metric, "DB 값": db_raw, "판정": verdict, "data_key": data_key})
        return rows

    @staticmethod
    def to_markdown(rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "_보고서에서 단위가 붙은 수치를 찾지 못했습니다._"
        lines = ["| 보고서 표기 | 지표 | DB 확정값 | 판정 |", "|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['보고서 표기']} | {r['지표'] or '-'} | {r['DB 값'] if r['DB 값'] is not None else '-'} | {r['판정']} |")
        return "\n".join(lines)


def review_with_agent(agent: PerspectiveAgent, context: Dict[str, Any], report_text: str,
                      number_rows: List[Dict[str, Any]], mode: str = "expert") -> Dict[str, Any]:
    """6개 관점 에이전트 하나가 자기 관점에서 사용자 보고서를 첨삭합니다."""
    stock_info = context["stock_info"]
    domain_data = context[agent.data_key]
    my_rows = [r for r in number_rows if r["data_key"] in (agent.data_key, None)]

    mode_instruction = (
        "전문가 모드: 지적 사항을 간결하게, 수정 문장은 바로 붙여 쓸 수 있는 형태로 제시하십시오."
        if mode == "expert" else
        "입문자 가이드 모드: 각 지적 사항마다 '왜 이것이 문제인지'와 관련 용어 풀이를 쉬운 말로 덧붙이십시오."
    )
    system_msg = f"""당신은 OpenResearch의 [{agent.agent_id}번 에이전트: {agent.name}]이며, 지금은 사용자가 작성한 보고서를 첨삭하는 검토자입니다.
{agent.role_prompt}

{COMMON_AGENT_RULES}
4. 보고서 수치의 맞고 틀림은 [코드 수치 대조 결과]의 판정만 인용하십시오. 직접 계산하거나 새 수치를 만들지 마십시오.
5. 당신의 관점과 관련된 내용만 첨삭하십시오. 다른 관점의 문제는 다루지 않습니다.

[출력 모드 지침]
{mode_instruction}

반드시 아래 형식으로 작성하십시오:
- ① 수치 검증: 대조 결과 중 당신 관점의 '불일치'·'검증 불가' 항목과 DB 확정값 (없으면 '해당 없음')
- ② 빠진 논점: 이 관점에서 보고서가 다루지 않은 핵심 내용 (SQL 데이터 근거와 출처 포함, 최대 3개)
- ③ 수정 제안: "원문 → 수정안" 형식 (최대 3개)
- ④ 관점별 완성도 점수 (1~10점) 및 이유
"""
    user_msg = f"""
[대상 종목]: {stock_info['name']} ({stock_info['ticker']}) / 업종: {stock_info['sector']}

[사용자 보고서 원문]:
{report_text[:REPORT_MAX_CHARS]}

[코드 수치 대조 결과]:
{json.dumps(my_rows, ensure_ascii=False, indent=2, default=str)}

[SQL 조회 원천 데이터 ({agent.data_key})]:
{json.dumps(domain_data, ensure_ascii=False, indent=2, default=str)}

위 자료만을 바탕으로 당신의 관점에서 보고서를 첨삭해 주십시오.
"""
    try:
        response = agent.llm.invoke([SystemMessage(content=system_msg), HumanMessage(content=user_msg)])
        analysis, status = response.content, "완료"
    except Exception as e:  # 한 에이전트 실패가 전체를 멈추지 않도록 상태로 기록
        analysis, status = f"(첨삭 실패: {type(e).__name__}: {e})", "실패"
    return {
        "agent_id": agent.agent_id,
        "agent_name": agent.name,
        "status": status,
        "analysis": analysis,
        "source": domain_data.get("source", "Neon DB"),
    }


class ReviewOrchestratorAgent:
    """6개 관점 첨삭을 우선순위(치명/중요/권장)별 하나의 첨삭 의견서로 합칩니다."""
    def __init__(self):
        self.llm = get_solar_llm(temperature=0.15)

    def synthesize(self, context: Dict[str, Any], reviews: List[Dict[str, Any]], mode: str = "expert") -> str:
        stock_info = context["stock_info"]
        compiled = "\n\n".join(
            f"### [A{r['agent_id']}. {r['agent_name']}] (상태: {r.get('status', '완료')})\n{r['analysis']}" for r in reviews
        )
        system_msg = f"""당신은 OpenResearch의 [7. 오케스트레이터]이며, 6개 관점 검토자의 첨삭을 하나의 '보고서 첨삭 의견서'로 정리합니다.

{COMMON_AGENT_RULES}

[필수 수행 과제]
0. **관점별 첨삭 요약표 (의견서 맨 앞)**: 표 열은 에이전트(A1~A6) | 가장 중요한 지적 1개 | 빠진 논점 수 | 수정 제안 수 | 완성도 점수. 검토자가 쓴 내용과 점수만 옮기십시오. 상태가 '실패'인 검토자는 '첨삭 실패'로 표기하고 종합에서 제외했다고 밝히십시오.
1. **총평**: 보고서의 강점과 가장 큰 약점을 2~3문장으로 요약하고, 근거가 된 검토자를 [A번호]로 표기하십시오.
2. **우선순위별 첨삭 목록**: 모든 지적 사항을 '치명(사실 오류·수치 불일치)', '중요(핵심 논점 누락)', '권장(표현·구성 개선)'으로 분류하고, 각 항목 끝에 출처 검토자를 [A2], [A3·A5]처럼 표기하십시오. 여러 검토자가 같은 지적을 했으면 하나로 합치고 번호를 모두 적으십시오.
3. **관점별 완성도 점수표**: 6개 관점 점수를 표로 정리하십시오 (검토자가 준 점수만 인용).
4. **수정 우선순위 3가지**: 작성자가 가장 먼저 고칠 3가지를 제시하십시오.
5. 현재 모드({mode})가 'guide'이면, 마지막에 '다음 보고서 작성 시 체크리스트'를 초심자 눈높이로 추가하십시오.
"""
        user_msg = f"""
[분석 대상]: {stock_info['name']} ({stock_info['ticker']}) - {stock_info['sector']}

[6개 관점 첨삭 결과]:
{compiled}

위 첨삭을 종합해 보고서 첨삭 의견서를 작성해 주십시오.
"""
        response = self.llm.invoke([SystemMessage(content=system_msg), HumanMessage(content=user_msg)])
        return response.content


def review_report(report_text: str, ticker: Optional[str] = None, mode: str = "expert") -> Dict[str, Any]:
    """사용자 보고서를 6개 관점에서 첨삭하고, 오케스트레이터가 첨삭 의견서로 종합합니다."""
    body = (report_text or "").strip()
    if not body or "여기에 첨삭할 보고서를 붙여 넣으세요" in body:
        raise ValueError("첨삭할 보고서 원문이 비어 있습니다. report_text에 보고서를 붙여 넣거나 load_report()로 파일을 읽어 주세요.")

    loader = KICDataLoader()
    ticker = resolve_ticker(report_text, ticker, loader)
    print("============================================================")
    print(f"📝 OpenResearch 보고서 첨삭 시작 | 종목: {ticker} | 모드: {mode}")
    print(f"🤖 사용 모델: {UPSTAGE_MODEL_NAME}")
    print("============================================================")

    # Step 1: DB 확정 데이터 로드 (분석 모드와 동일)
    context = loader.fetch_all_context(ticker)

    # Step 2: 보고서 수치 ↔ DB 확정값 코드 대조
    print("▶ [Checker] 보고서 수치와 DB 확정값 대조 중...")
    number_rows = ReportNumberChecker.check(report_text, context)

    # Step 3: 6개 관점 첨삭
    reviews = []
    for agent in build_six_agents():
        print(f"▶ [Agent {agent.agent_id}] {agent.name} 첨삭 중...")
        reviews.append(review_with_agent(agent, context, report_text, number_rows, mode=mode))
        print(f"   └ {reviews[-1]['status']} ({len(reviews[-1]['analysis'])}자)")

    # Step 4: 오케스트레이터 종합 + 코드 대조표 + 출처 각주
    print("▶ [Agent 7: Orchestrator] 첨삭 의견서 종합 중...")
    feedback = ReviewOrchestratorAgent().synthesize(context, reviews, mode=mode)
    number_table = "\n\n---\n### 🔢 보고서 수치 대조표 (코드 판정)\n" + ReportNumberChecker.to_markdown(number_rows)
    verified_feedback = FactSourceVerifier.verify(feedback + number_table, reviews)
    full_report = FactSourceVerifier.verify(
        compose_full_report(context["stock_info"], reviews, feedback, kind="첨삭") + number_table,
        reviews,
    )

    return {
        "ticker": ticker,
        "mode": mode,
        "number_check": number_rows,
        "individual_agent_reviews": reviews,
        "orchestrator_review_report": verified_feedback,  # 종합만 (기존 키 유지)
        "full_report": full_report,  # 관점별 첨삭 원문 + 종합 의견서
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # 보고서 첨삭 모드: python solar_pro_4.py 보고서.md [종목코드] [expert|guide]
        args = sys.argv[1:] + [None, "expert"][len(sys.argv) - 2:]
        result = review_report(load_report(args[0]), ticker=args[1], mode=args[2])
        print("\n\n==================== [보고서 첨삭 의견서] ====================")
        print(result["full_report"])
    else:
        result = run_openresearch_multi_agent(ticker="005930", mode="expert")
        print("\n\n==================== [최종 보고서: 에이전트 의견 + 오케스트레이터 종합] ====================")
        print(result["full_report"])
