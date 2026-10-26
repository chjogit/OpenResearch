"""A4 투자심리·수급.

근거를 네 계열로 나눠 계산합니다. 같은 계열 안의 지표는 같은 사건을 반영할 수 있으므로 독립 근거로 세지 않습니다.
- 수급: 외국인·기관·개인 5·20·60일 순매수(수량, 종가 기준 금액 근사), 거래대금 대비 순매수 강도,
        연속 순매수·순매도 일수, 외국인 지분율 변화와 1년 범위 내 위치
- 논조: 뉴스·블로그·카페 문서 감성(키워드 사전 점수)을 문서에서 직접 집계 (최근 7일 vs 직전 8~30일)
- 관심: 네이버 검색 관심도(최근 7일 ÷ 직전 90일, 1년 내 위치). 문서 수는 수집 범위가 바뀌면 함께 바뀌므로 쓰지 않음
- 가격·시장: 20·60일 수익률, 코스피 대비 초과 수익률, VIX(시장 공포 지표)
그리고 수급과 가격이 엇갈리는지(예: 주가 하락 중 외국인 순매수)를 규칙으로 표시합니다.

한계: 감성 점수는 키워드 사전 기반이며 학습 모델 성능이 검증된 값이 아닙니다. 순매수 기록만으로
매수 의도나 정보 보유를 추정하지 않습니다. 대차잔고(공매도 대용)는 수집 테이블이 비어 있으면 무자료입니다.
"""
from __future__ import annotations

from .facts import Facts, daily_returns, pct_change, percentile_rank, series_points, streak

SQL = """
SELECT json_build_object(
    'flows', (SELECT json_agg(x ORDER BY x.d DESC) FROM (
        SELECT f.trade_date AS d, f.foreign_net_qty AS fq, f.institution_net_qty AS iq, f.individual_net_qty AS pq,
               f.foreign_hold_pct AS hold, p.close, p.trade_value AS tv
        FROM core.investor_flow_daily f
        LEFT JOIN core.price_daily p ON p.company_id = f.company_id AND p.trade_date = f.trade_date
        WHERE f.company_id = %(cid)s AND f.trade_date <= %(as_of)s::date
        ORDER BY f.trade_date DESC LIMIT 260) x),
    'price', (SELECT json_agg(json_build_object('d', trade_date, 'v', close) ORDER BY trade_date)
              FROM core.price_daily WHERE company_id = %(cid)s AND trade_date <= %(as_of)s::date
                AND trade_date > %(as_of)s::date - INTERVAL '120 days'),
    'kospi', (SELECT json_agg(json_build_object('d', trade_date, 'v', close) ORDER BY trade_date)
              FROM core.market_index_daily WHERE symbol = '^KS11' AND trade_date <= %(as_of)s::date
                AND trade_date > %(as_of)s::date - INTERVAL '120 days'),
    'vix', (SELECT json_agg(json_build_object('d', trade_date, 'v', close) ORDER BY trade_date)
            FROM core.market_index_daily WHERE symbol = '^VIX' AND trade_date <= %(as_of)s::date
              AND trade_date > %(as_of)s::date - INTERVAL '400 days'),
    'docs', (SELECT json_agg(x) FROM (
        SELECT d.published_at::date AS d, d.source, count(s.score) AS n, avg(s.score) AS score
        FROM rag.document d JOIN core.doc_sentiment s USING (doc_id)
        WHERE d.company_id = %(cid)s AND d.published_at::date <= %(as_of)s::date
          AND d.published_at::date > %(as_of)s::date - 30
        GROUP BY 1, 2) x),
    'search', (SELECT json_agg(json_build_object('d', trade_date, 'v', ratio) ORDER BY trade_date)
               FROM core.search_trend WHERE subject = 'KR:' || %(ticker)s AND trade_date <= %(as_of)s::date
                 AND trade_date > %(as_of)s::date - INTERVAL '400 days'),
    'lending', (SELECT json_agg(json_build_object('d', trade_date, 'v', balance_qty) ORDER BY trade_date)
                FROM (SELECT trade_date, balance_qty FROM core.stock_lending_daily
                      WHERE company_id = %(cid)s AND trade_date <= %(as_of)s::date
                      ORDER BY trade_date DESC LIMIT 60) l)
) AS bundle
"""

SRC_FLOW = "core.investor_flow_daily (네이버 투자자별 매매)"
SRC_DOC = "rag.document × core.doc_sentiment (키워드 사전)"
WHO = (("외국인", "fq"), ("기관", "iq"), ("개인", "pq"))
MIN_DOCS = 5
MIN_PRIOR_DOCS = 20


def params(co: dict, as_of: str) -> dict:
    return {"cid": co["company_id"], "ticker": co["ticker"], "as_of": as_of}


def _days_back(day: str, n: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(day) - timedelta(days=n)).isoformat()


def compute(b: dict, co: dict, as_of: str) -> dict:
    f = Facts("S")
    rows = b.get("flows") or []  # 최신순
    for r in rows:
        r["d"] = str(r["d"])[:10]
    period = "-"

    # 1) 수급
    g = "수급"
    if not rows:
        f.gap("투자자별 수급", "수집 데이터 없음")
    else:
        period = f"수급 {rows[-1]['d']}~{rows[0]['d']} ({len(rows)}거래일)"
        d0 = rows[0]["d"]
        for who, col in WHO:
            for n in (5, 20, 60):
                if len(rows) < n:
                    continue
                win = rows[:n]
                f.add(f"{who} {n}일 순매수 수량", sum(r[col] or 0 for r in win), "주", d0, SRC_FLOW, kind="calc", group=g)
                if n == 20 and all(r.get("close") for r in win):
                    amt = sum((r[col] or 0) * r["close"] for r in win)
                    f.add(f"{who} 20일 순매수 금액(근사)", amt, "KRW±", d0, SRC_FLOW + " × 종가", kind="proxy", group=g,
                          note="일별 순매수 수량 × 종가")
                    tv = sum(r["tv"] or 0 for r in win)
                    if tv and all(r.get("tv") for r in win):
                        f.add(f"{who} 20일 순매수 강도(거래대금 대비)", amt / tv * 100, "%", d0,
                              SRC_FLOW + " × core.price_daily", kind="proxy", group=g,
                              note="순매수 금액 근사 ÷ 같은 기간 거래대금. 종목 간 비교용")
            s = streak([r[col] for r in rows])
            if s:
                k = f.add(f"{who} 연속 순{'매수' if s > 0 else '매도'} 일수", abs(s), "일", d0, SRC_FLOW, kind="calc",
                          group=g)
                if who != "개인" and abs(s) >= 5 and k:
                    f.flag(f"{who} {abs(s)}거래일 연속 순{'매수' if s > 0 else '매도'} ({{{k}}})")
        # 외국인 순매수일 평균 가격(근사) 대비 현재가: 최근 60일 중 외국인이 순매수한 날의 수량 가중 종가
        win = [r for r in rows[:60] if (r["fq"] or 0) > 0 and r.get("close")]
        if len(win) >= 10 and rows[0].get("close"):
            avg_px = sum(r["fq"] * r["close"] for r in win) / sum(r["fq"] for r in win)
            k_ap = f.add("외국인 순매수일 평균 가격(60일, 근사)", avg_px, "KRW", d0, SRC_FLOW + " × 종가", kind="proxy",
                         group=g, note=f"순매수한 {len(win)}일의 순매수 수량 가중 종가. 실제 매입 단가가 아님")
            k_gap = f.add("현재가의 외국인 순매수 평균 가격 대비", pct_change(rows[0]["close"], avg_px), "%chg", d0,
                          SRC_FLOW + " × 종가", kind="proxy", group=g)
            if k_ap and k_gap:
                above = rows[0]["close"] >= avg_px
                f.flag(f"현재가가 외국인 순매수일 평균 가격(근사)보다 {'높음' if above else '낮음'} ({{{k_gap}}})")
        holds = [r["hold"] for r in rows if r.get("hold") is not None]
        if holds:
            f.add("외국인 지분율", holds[0], "%", d0, SRC_FLOW, group=g)
            for n in (20, 60):
                if len(holds) >= n:
                    f.add(f"외국인 지분율 {n}일 변화", holds[0] - holds[n - 1], "%p", d0, SRC_FLOW, kind="calc", group=g)
            if len(holds) >= 120:
                lo, hi = min(holds), max(holds)
                pos = None if hi == lo else (holds[0] - lo) / (hi - lo) * 100
                f.add(f"외국인 지분율 {len(holds)}일 범위 내 위치", pos, "pctile", d0, SRC_FLOW, kind="calc", group=g,
                      note="0=기간 최저, 100=기간 최고")

    # 2) 가격·시장
    g = "가격·시장"
    px = series_points(b.get("price"))
    ks = series_points(b.get("kospi"))
    ret = {}
    for n in (20, 60):
        if len(px) > n:
            ret[n] = (px[-1][1] / px[-1 - n][1] - 1) * 100
            f.add(f"{n}일 주가 수익률", ret[n], "%chg", px[-1][0], "core.price_daily", kind="calc", group=g)
            if len(ks) > n:
                kr = (ks[-1][1] / ks[-1 - n][1] - 1) * 100
                f.add(f"{n}일 코스피 대비 초과 수익률", ret[n] - kr, "%p", px[-1][0], "core.price_daily × ^KS11",
                      kind="calc", group=g)
    if px and len(daily_returns(px)) < len(px) - 1:
        f.flag("데이터 점검: 가격제한폭을 넘는 하루 가격 변화가 있어 수익률 계산에서 제외함 (액면분할 등 확인 필요)")
    vix = series_points(b.get("vix"))
    if vix:
        k_v = f.add("VIX(미국 시장 변동성 지수)", vix[-1][1], "idx", vix[-1][0], "core.market_index_daily ^VIX",
                    group=g)
        pr = percentile_rank([v for _, v in vix], vix[-1][1])
        f.add("VIX 1년 내 위치", pr, "pctile", vix[-1][0], "core.market_index_daily ^VIX", kind="calc", group=g)
        if pr is not None and pr >= 80 and k_v:
            f.flag(f"시장 전반 위험 회피가 높은 편 (VIX {{{k_v}}}, 1년 상위권)")

    # 수급 × 가격 엇갈림
    fk, rk = f.key_of("외국인 20일 순매수 수량"), f.key_of("20일 주가 수익률")
    if fk and rk:
        fv, rv = f.items[fk]["value"], f.items[rk]["value"]
        if fv > 0 > rv:
            f.flag(f"엇갈림: 주가 하락 중 외국인 순매수 ({{{rk}}}, {{{fk}}})")
        elif fv < 0 < rv:
            f.flag(f"엇갈림: 주가 상승 중 외국인 순매도 ({{{rk}}}, {{{fk}}})")

    # 3) 논조 (문서 감성)
    g = "논조(감성)"
    docs = b.get("docs") or []
    cut7 = _days_back(as_of, 7)
    by_src: dict[str, dict[str, list]] = {}
    for r in docs:
        side = "recent" if str(r["d"])[:10] > cut7 else "prior"
        if not r.get("n") or r.get("score") is None:
            continue  # 점수가 붙은 문서가 없는 날
        by_src.setdefault(r["source"], {"recent": [], "prior": []})[side].append((int(r["n"]), float(r["score"]),
                                                                               str(r["d"])[:10]))
    names = {"naver_news": "뉴스", "naver_blog": "블로그", "naver_cafe": "카페", "finnhub_news": "영문 뉴스",
             "youtube_comment": "유튜브 댓글"}
    for src, name in names.items():
        part = by_src.get(src)
        if not part:
            continue
        rn = sum(n for n, _, _ in part["recent"])
        pn = sum(n for n, _, _ in part["prior"])
        days_prior = len({d for _, _, d in part["prior"]})
        if rn >= MIN_DOCS:
            rs = sum(n * s for n, s, _ in part["recent"]) / rn
            f.add(f"{name} 감성(최근 7일)", rs, "score", as_of, SRC_DOC, kind="calc", group=g,
                      note=f"문서 {rn}건, -1 부정 ~ +1 긍정, 키워드 사전 기반")
            if pn >= MIN_PRIOR_DOCS and days_prior >= 7:
                ps = sum(n * s for n, s, _ in part["prior"]) / pn
                kd = f.add(f"{name} 감성 변화(최근 7일 − 직전 8~30일)", rs - ps, "score", as_of, SRC_DOC, kind="calc",
                           group=g)
                if kd and abs(rs - ps) >= 0.1:
                    f.flag(f"{name} 논조 {'개선' if rs > ps else '악화'} ({{{kd}}})")
            else:
                f.gap(f"{name} 감성 변화", f"직전 기간 문서 {pn}건·{days_prior}일뿐 (수집 기간 짧음)")
        else:
            f.gap(f"{name} 감성(최근 7일)", f"점수 붙은 문서 {rn}건 (최소 {MIN_DOCS}건)")
    # 문서 수는 관심 지표로 쓰지 않음: 수집 범위·주기가 바뀌면 문서 수가 같이 바뀌어 관심 변화로 착각하기 쉬움
    if not docs:
        f.gap("문서 감성", "최근 30일 문서 없음")

    g = "관심"
    sr = series_points(b.get("search"))
    if len(sr) >= 97:
        last7 = [v for _, v in sr[-7:]]
        prev90 = [v for _, v in sr[-97:-7]]
        avg90 = sum(prev90) / len(prev90)
        k_s = f.add("검색 관심도 배율(최근 7일 ÷ 직전 90일)", (sum(last7) / 7) / avg90 if avg90 else None, "배",
                    sr[-1][0], "core.search_trend (네이버 데이터랩)", kind="calc", group=g,
                    note="1보다 크면 관심 증가")
        f.add("검색 관심도 1년 내 위치(최근 7일 평균)", percentile_rank([v for _, v in sr], sum(last7) / 7), "pctile",
              sr[-1][0], "core.search_trend (네이버 데이터랩)", kind="calc", group=g)
        if k_s and avg90 and (sum(last7) / 7) / avg90 >= 2:
            f.flag(f"검색 관심 급증 ({{{k_s}}})")
    else:
        f.gap("검색 관심도", "관측 97일 미만")

    # 대차잔고
    lend = series_points(b.get("lending"))
    if len(lend) >= 20:
        f.add("대차잔고(주식 수)", lend[-1][1], "주", lend[-1][0], "core.stock_lending_daily", group="수급")
        f.add("대차잔고 20일 변화율", pct_change(lend[-1][1], lend[-20][1]), "%chg", lend[-1][0],
              "core.stock_lending_daily", kind="calc", group="수급", note="공매도 선행 지표로 쓰는 대용치")
    else:
        f.gap("주식대차 잔고(공매도 대용)", "core.stock_lending_daily 20일 미만 (금융위 서버 접속 문제로 수집 지연)")
    f.note("근거 계열: 수급 / 논조 / 관심 / 가격·시장. 같은 계열 안의 지표는 하나의 근거로 센다.")
    return {"facts": f, "docs": [], "period": period}
