"""에이전트 3 투자심리·수급 (교재 9장, 기초기획서 R4).

근거를 네 계열로 나눠 계산합니다. 같은 계열 안의 지표는 같은 사건을 반영할 수 있으므로 독립 근거로 세지 않습니다.
- 수급: 외국인·기관·개인 5·20·60일 순매수(수량, 종가 기준 금액 근사), 거래대금 대비 순매수 강도,
        연속 순매수·순매도 일수, 외국인 지분율 변화와 1년 범위 내 위치
- 논조: 뉴스·블로그·카페 문서 감성(키워드 사전 점수)을 문서에서 직접 집계 (최근 7일 vs 직전 8~30일)
- 관심: 네이버 검색 관심도(최근 7일 ÷ 직전 90일, 1년 내 위치). 문서 수는 수집 범위가 바뀌면 함께 바뀌므로 쓰지 않음
- 거래: 거래대금 최근 5일 평균 ÷ 직전 60일 평균
- 가격·시장: 20·60일 수익률, 코스피 대비 초과 수익률, VIX(시장 공포 지표)
그리고 수급과 가격이 엇갈리는지(예: 주가 하락 중 외국인 순매수)를 규칙으로 표시합니다.

기초기획서 R4 대응
- 기준선 비교: 신호마다 '평소'(직전 60일·90일·8~30일)를 규칙 기준선으로 두고 현재 값과 나란히 보여 줍니다.
  감성은 키워드 사전 기준선이며 학습 모델이 아닙니다 (성능 미검증 상태를 출력에 명시).
- 중복 신호: 최근 창(5~7일)에 뉴스 논조·검색 관심·거래대금·집중 매매 이상 징후가 둘 이상 함께 나타나면
  같은 사건을 반영할 수 있으므로 하나의 '사건 묶음'(X1)으로 묶고, 독립 근거로 중복 계산하지 않습니다.

한계: 감성 점수는 키워드 사전 기반이며 학습 모델 성능이 검증된 값이 아닙니다. 순매수 기록만으로
매수 의도나 정보 보유를 추정하지 않습니다. 대차잔고(공매도 대용)는 수집 테이블이 비어 있으면 무자료입니다.
"""
from __future__ import annotations

from .facts import Facts, check_freshness, daily_returns, pct_change, percentile_rank, series_points, streak

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
                AND trade_date > %(as_of)s::date - INTERVAL '200 days'),
    'kospi', (SELECT json_agg(json_build_object('d', trade_date, 'v', close) ORDER BY trade_date)
              FROM core.market_index_daily WHERE symbol = '^KS11' AND trade_date <= %(as_of)s::date
                AND trade_date > %(as_of)s::date - INTERVAL '200 days'),
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
DEFAULT_PERIOD = 20
MAX_PERIOD = 120
Z_ALERT = 2.0          # 최근 5일 순매수 강도가 직전 60일 분포에서 이만큼 벗어나면 '집중 매매'
SENT_JUMP = 0.15       # 감성 점수 변화가 이 이상이면 '논조 급변'
LEND_JUMP = 20.0       # 대차잔고 20일 변화율(%)이 이 이상이면 '대차잔고 급증'
TV_JUMP = 2.0          # 거래대금 최근 5일 평균이 직전 60일 평균의 이 배수 이상이면 '거래대금 급증'
SEARCH_JUMP = 2.0      # 검색 관심도 배율이 이 이상이면 '검색 관심 급증'
SENT_MODEL = "키워드 감성 사전 기준선 (학습 모델 아님, 성능 미검증)"
# 같은 사건을 반영할 수 있는 최근 창 신호 (대차잔고는 20일 신호라 제외)
EVENT_SIGNALS = ("뉴스 논조", "블로그 논조", "카페 논조", "검색 관심", "거래대금", "외국인 집중 매매", "기관 집중 매매")


def params(co: dict, as_of: str) -> dict:
    return {"cid": co["company_id"], "ticker": co["ticker"], "as_of": as_of}


def _days_back(day: str, n: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(day) - timedelta(days=n)).isoformat()


def _intensity_z(rows: list[dict], col: str) -> tuple[float, float, int, float] | None:
    """최근 5거래일 평균 순매수 강도(거래대금 대비 %)와, 직전 60거래일 분포 대비 표준점수."""
    daily = [(r[col] or 0) * r["close"] / r["tv"] * 100 for r in rows[:65] if r.get("close") and r.get("tv")]
    if len(daily) < 65:
        return None
    recent, base = daily[:5], daily[5:65]
    mu = sum(base) / len(base)
    sd = (sum((x - mu) ** 2 for x in base) / (len(base) - 1)) ** 0.5
    m5 = sum(recent) / 5
    if not sd:
        return None
    return m5, (m5 - mu) / (sd / 5 ** 0.5), len(base), mu


def compute(b: dict, co: dict, as_of: str, period: int | None = None, **_) -> dict:
    """period: 사용자가 정한 관찰 기간(거래일). 기본 20일. 5·20·60일은 항상 계산하고 period 를 더합니다."""
    f = Facts("S")
    P = max(5, min(int(period or DEFAULT_PERIOD), MAX_PERIOD))
    windows = sorted({5, 20, 60, P})
    anomalies: list[str] = []
    baseline: list[dict] = []       # 기준선 비교표 행
    fired: dict[str, list[str]] = {}  # 최근 창에 이상 징후가 난 신호 → 근거 키
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
        check_freshness(f, "투자자별 수급", rows[0]["d"], as_of, 5)
        d0 = rows[0]["d"]
        for who, col in WHO:
            for n in windows:
                if len(rows) < n:
                    continue
                win = rows[:n]
                f.add(f"{who} {n}일 순매수 수량", sum(r[col] or 0 for r in win), "주", d0, SRC_FLOW, kind="calc", group=g)
                if n in (20, P) and all(r.get("close") for r in win):
                    amt = sum((r[col] or 0) * r["close"] for r in win)
                    f.add(f"{who} {n}일 순매수 금액(근사)", amt, "KRW±", d0, SRC_FLOW + " × 종가", kind="proxy", group=g,
                          note="일별 순매수 수량 × 종가")
                    tv = sum(r["tv"] or 0 for r in win)
                    if tv and all(r.get("tv") for r in win):
                        f.add(f"{who} {n}일 순매수 강도(거래대금 대비)", amt / tv * 100, "%", d0,
                              SRC_FLOW + " × core.price_daily", kind="proxy", group=g,
                              note="순매수 금액 근사 ÷ 같은 기간 거래대금. 종목 간 비교용")
            if who != "개인":  # 이상 징후: 집중 매매
                z = _intensity_z(rows, col)
                if z:
                    m5, zz, nb, mu = z
                    k5 = f.add(f"{who} 최근 5일 순매수 강도 평균(거래대금 대비)", m5, "%", d0,
                               SRC_FLOW + " × core.price_daily", kind="proxy", group=g)
                    kb = f.add(f"{who} 직전 60일 일별 순매수 강도 평균(기준선)", mu, "%", d0,
                               SRC_FLOW + " × core.price_daily", kind="calc", group=g)
                    kz = f.add(f"{who} 최근 5일 강도의 직전 60일 대비 표준점수", zz, "coef", d0,
                               SRC_FLOW + " × core.price_daily", kind="calc", group=g,
                               note=f"직전 {nb}거래일 일별 강도의 평균·표준편차 기준. 절댓값 {Z_ALERT:g} 이상이면 이례적")
                    hit = bool(k5 and kz and abs(zz) >= Z_ALERT)
                    if hit:
                        text = (f"이상 징후: {who} 집중 순{'매수' if zz > 0 else '매도'} "
                                f"(최근 5일 강도 {{{k5}}}, 표준점수 {{{kz}}})")
                        f.flag(text)
                        anomalies.append(text)
                        fired[f"{who} 집중 매매"] = [k for k in (k5, kz) if k]
                    baseline.append({"signal": f"{who} 순매수 강도", "method": "규칙: 직전 60거래일 평균·표준편차",
                                     "current": k5, "base": kb, "measure": kz,
                                     "status": "기준선 대비 이례적" if hit else "평소 범위",
                                     "rule": f"표준점수 절댓값 {Z_ALERT:g} 이상이면 이례적"})
                else:
                    f.gap(f"{who} 집중 매매 점검", "강도 계산에 필요한 65거래일 미만")
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
                f.add(f"외국인 지분율 {len(holds)}일 범위 내 위치(최저 0 ~ 최고 100)", pos, "pos", d0, SRC_FLOW, kind="calc",
                      group=g, note="백분위가 아니라 기간 최저~최고 사이의 위치")

    # 1-1) 거래대금 (뉴스와 같은 사건을 반영하기 쉬운 신호)
    g = "거래"
    tvs = [r["tv"] for r in rows[:65] if r.get("tv")]
    if len(tvs) >= 65:
        m5, b60 = sum(tvs[:5]) / 5, sum(tvs[5:65]) / 60
        k_m = f.add("거래대금 최근 5일 평균", m5, "KRW", rows[0]["d"], "core.price_daily", kind="calc", group=g)
        k_b = f.add("거래대금 직전 60일 평균(기준선)", b60, "KRW", rows[0]["d"], "core.price_daily", kind="calc", group=g)
        k_t = f.add("거래대금 배율(최근 5일 ÷ 직전 60일)", m5 / b60 if b60 else None, "배", rows[0]["d"],
                    "core.price_daily", kind="calc", group=g, note="1보다 크면 평소보다 거래가 많음")
        hit = bool(k_t and b60 and m5 / b60 >= TV_JUMP)
        if hit:
            text = f"이상 징후: 거래대금 급증 ({{{k_t}}})"
            f.flag(text)
            anomalies.append(text)
            fired["거래대금"] = [k_t]
        baseline.append({"signal": "거래대금", "method": "규칙: 직전 60거래일 평균", "current": k_m, "base": k_b,
                         "measure": k_t, "status": "기준선 대비 이례적" if hit else "평소 범위",
                         "rule": f"배율 {TV_JUMP:g} 이상이면 이례적"})
    elif rows:
        f.gap("거래대금 기준선", "거래대금이 있는 거래일 65일 미만")

    # 2) 가격·시장
    g = "가격·시장"
    px = series_points(b.get("price"))
    ks = series_points(b.get("kospi"))
    ret = {}
    for n in sorted({20, 60, P}):
        if len(px) > n:
            ret[n] = (px[-1][1] / px[-1 - n][1] - 1) * 100
            f.add(f"{n}일 주가 수익률", ret[n], "%chg", px[-1][0], "core.price_daily", kind="calc", group=g)
            if len(ks) > n:
                kr = (ks[-1][1] / ks[-1 - n][1] - 1) * 100
                k_ex = f.add(f"{n}일 코스피 대비 초과 수익률", ret[n] - kr, "%p", px[-1][0], "core.price_daily × ^KS11",
                             kind="calc", group=g, note="+면 코스피보다 나음(덜 하락 또는 더 상승), -면 코스피보다 못함")
                if k_ex:
                    f.flag(f"{n}일 코스피 대비: {'상회' if ret[n] >= kr else '하회'} ({{{k_ex}}})")
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
            kr = f.add(f"{name} 감성(최근 7일)", rs, "score", as_of, SRC_DOC, kind="calc", group=g,
                       note=f"문서 {rn}건, -1 부정 ~ +1 긍정, 키워드 사전 기반")
            if pn >= MIN_PRIOR_DOCS and days_prior >= 7:
                ps = sum(n * s for n, s, _ in part["prior"]) / pn
                kp = f.add(f"{name} 감성(직전 8~30일, 기준선)", ps, "score", as_of, SRC_DOC, kind="calc", group=g,
                           note=f"문서 {pn}건")
                kd = f.add(f"{name} 감성 변화(최근 7일 − 직전 8~30일)", rs - ps, "score", as_of, SRC_DOC, kind="calc",
                           group=g)
                hit = bool(kd and abs(rs - ps) >= SENT_JUMP)
                if src in ("naver_news", "naver_blog", "naver_cafe"):
                    baseline.append({"signal": f"{name} 논조", "method": "사전: " + SENT_MODEL + ", 직전 8~30일 대비",
                                     "current": kr, "base": kp, "measure": kd,
                                     "status": "기준선 대비 이례적" if hit else "평소 범위",
                                     "rule": f"변화 절댓값 {SENT_JUMP:g} 이상이면 이례적"})
                if hit:
                    text = f"이상 징후: {name} 논조 급격한 {'개선' if rs > ps else '악화'} ({{{kd}}})"
                    f.flag(text)
                    anomalies.append(text)
                    fired[f"{name} 논조"] = [kd]
                elif kd and abs(rs - ps) >= 0.1:
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
        hit = bool(k_s and avg90 and (sum(last7) / 7) / avg90 >= SEARCH_JUMP)
        if hit:
            text = f"이상 징후: 검색 관심 급증 ({{{k_s}}})"
            f.flag(text)
            anomalies.append(text)
            fired["검색 관심"] = [k_s]
        if k_s:
            baseline.append({"signal": "검색 관심도", "method": "규칙: 직전 90일 평균", "current": None, "base": None,
                             "measure": k_s, "status": "기준선 대비 이례적" if hit else "평소 범위",
                             "rule": f"배율 {SEARCH_JUMP:g} 이상이면 이례적"})
    else:
        f.gap("검색 관심도", "관측 97일 미만")

    # 대차잔고
    lend = series_points(b.get("lending"))
    if len(lend) >= 20:
        f.add("대차잔고(주식 수)", lend[-1][1], "주수", lend[-1][0], "core.stock_lending_daily", group="수급")
        chg = pct_change(lend[-1][1], lend[-20][1])
        k_l = f.add("대차잔고 20일 변화율", chg, "%chg", lend[-1][0],
                    "core.stock_lending_daily", kind="calc", group="수급", note="공매도 선행 지표로 쓰는 대용치")
        hit = bool(k_l and chg is not None and chg >= LEND_JUMP)
        if hit:
            text = f"이상 징후: 대차잔고 급증 ({{{k_l}}})"
            f.flag(text)
            anomalies.append(text)
        if k_l:
            baseline.append({"signal": "대차잔고", "method": "규칙: 20거래일 전 대비", "current": None, "base": None,
                             "measure": k_l, "status": "기준선 대비 이례적" if hit else "평소 범위",
                             "rule": f"20일 변화율 {LEND_JUMP:g}% 이상이면 이례적"})
    else:
        f.gap("주식대차 잔고(공매도 대용)", "core.stock_lending_daily 20일 미만 (금융위 서버 접속 문제로 수집 지연)")
    f.note("근거 계열: 수급 / 거래 / 논조 / 관심 / 가격·시장. 같은 계열 안의 지표는 하나의 근거로 센다.")
    f.note("감성 점수는 " + SENT_MODEL + "입니다. 긍정 문서가 많다는 것과 향후 수익률이 높다는 것은 별개의 가설입니다.")
    f.note("순매수 기록만으로 매수 의도·정보 보유를 추정하지 않습니다.")
    clusters = duplicate_clusters(fired)
    for c in clusters:
        keys = " ".join("{" + k + "}" for k in c["keys"])
        f.flag(f"중복 신호 주의: {'·'.join(c['signals'])}이(가) 최근 같은 기간에 함께 나타남. 같은 사건을 반영할 수 있어 "
               f"독립 근거로 세지 않고 하나의 사건 묶음({c['id']})으로 봄 ({keys})")
    if P not in (5, 20, 60):
        f.note(f"사용자 관찰 기간: {P}거래일")
    return {"facts": f, "docs": [], "period": period, "anomalies": anomalies, "summary": summary_rows(f, P),
            "obs_period": P, "baseline": baseline, "dup_clusters": clusters, "sentiment_model": SENT_MODEL}


def duplicate_clusters(fired: dict[str, list[str]]) -> list[dict]:
    """최근 창에 함께 나타난 이상 징후 신호를 하나의 사건 묶음으로 묶습니다 (둘 이상일 때만).
    뉴스·검색(정보)과 거래대금·집중 매매(거래)는 같은 사건의 두 얼굴일 수 있습니다 (교재 9장)."""
    sig = [s for s in EVENT_SIGNALS if s in fired]
    if len(sig) < 2:
        return []
    return [{"id": "X1", "signals": sig, "keys": [k for s in sig for k in fired[s]],
             "members": {s: list(fired[s]) for s in sig}}]


SUMMARY = (  # (계열, 장부 항목 이름 틀) — 기간 P 는 사용자 입력
    ("수급", "외국인 {P}일 순매수 수량"), ("수급", "외국인 {P}일 순매수 강도(거래대금 대비)"),
    ("수급", "기관 {P}일 순매수 수량"), ("수급", "개인 {P}일 순매수 수량"),
    ("수급", "외국인 지분율 20일 변화"), ("수급", "대차잔고 20일 변화율"),
    ("거래", "거래대금 배율(최근 5일 ÷ 직전 60일)"),
    ("논조", "뉴스 감성(최근 7일)"), ("논조", "뉴스 감성 변화(최근 7일 − 직전 8~30일)"),
    ("논조", "블로그 감성(최근 7일)"), ("논조", "카페 감성(최근 7일)"),
    ("관심", "검색 관심도 배율(최근 7일 ÷ 직전 90일)"),
    ("가격·시장", "{P}일 주가 수익률"), ("가격·시장", "{P}일 코스피 대비 초과 수익률"),
    ("가격·시장", "VIX(미국 시장 변동성 지수)"),
)


def summary_rows(f: Facts, P: int) -> list[dict]:
    """심리·수급 요약표의 행 (코드가 만든 표, LLM 무관). 판정은 그 키가 들어간 코드 판정 문장."""
    out = []
    for group, label in SUMMARY:
        k = f.key_of(label.format(P=P))
        if not k:
            continue
        verdict = next((fl for fl in f.flags if "{" + k + "}" in fl), "")
        out.append({"group": group, "key": k, "label": f.items[k]["label"], "verdict": verdict})
    return out
