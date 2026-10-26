"""A2 재무·밸류에이션·건전성.

계산하는 것
- TTM 실적·이익률·ROE·부채비율, PER(TTM)과 PER(연간 FY)을 서로 다른 키로 분리
- 분기 추세: 최근 분기 전년 동기·전 분기 대비, 최근 4개 분기 영업이익률 흐름, 매출 전년 대비 연속 증가 분기 수,
  TTM 매출 전년 대비(분기 8개 이상일 때)
- 자기 PER 밴드: 분기말 시가총액 ÷ 그 분기까지의 TTM 순이익. 현재 PER이 과거 분기말 PER 중 몇 백분위인지
- 실제 Peer 비교: Peer 그룹 종목의 TTM 지표 중앙값과 이 종목의 Peer 내 백분위
- 현금흐름(연간): 영업현금흐름, 설비투자, 잉여현금흐름(FCF), 배당·자사주, 이자보상배율 대용치
- 규칙 기반 경고: 순손실, 자본잠식, 부채비율 200% 초과, 이자보상배율 대용치 1 미만, 영업현금흐름 적자, FCF 적자,
  분기 합계와 TTM 불일치(데이터 정합성)

한계: v_ttm·Peer 값은 최신 시점 뷰라 과거 시점(as_of) 평가에는 쓰지 않습니다. PER 밴드는 분기말 기준이며
실적 발표 지연을 반영하지 않습니다.
"""
from __future__ import annotations

from itertools import pairwise

from .facts import Facts, median, pct_change, percentile_rank
from .macro import FINANCIAL_SECTORS, sector_of

SQL = """
WITH pg AS (
    SELECT peer_group_id FROM core.peer_group WHERE base_company_id = %(cid)s ORDER BY created_at DESC LIMIT 1
), qe AS (
    SELECT DISTINCT period_end AS pe FROM core.financial_quarter
    WHERE company_id = %(cid)s AND period_end <= %(as_of)s::date
    UNION SELECT %(as_of)s::date
)
SELECT json_build_object(
    'ttm', (SELECT row_to_json(t) FROM (
        SELECT ttm_end, bs_end, revenue_ttm, operating_income_ttm, net_income_ttm, op_margin_ttm, roe_ttm,
               debt_ratio, per_ttm, pbr, assets, liabilities, equity, currency
        FROM core.v_ttm WHERE market = 'KR' AND ticker = %(ticker)s) t),
    'quarters', (SELECT json_agg(x ORDER BY x.period_end) FROM (
        SELECT period_end, fiscal_year, fiscal_q, json_object_agg(metric, amount) AS m
        FROM core.financial_quarter
        WHERE company_id = %(cid)s AND period_end <= %(as_of)s::date
        GROUP BY period_end, fiscal_year, fiscal_q) x),
    'valuation', (SELECT row_to_json(v) FROM (
        SELECT fiscal_year, price_date, per, pbr FROM core.v_valuation
        WHERE market = 'KR' AND ticker = %(ticker)s ORDER BY fiscal_year DESC LIMIT 1) v),
    'annual', (SELECT json_agg(a ORDER BY a.fiscal_year) FROM (
        SELECT fiscal_year, revenue, operating_income, net_income FROM core.v_fundamentals_annual
        WHERE company_id = %(cid)s) a),
    'cash', (SELECT json_agg(c) FROM (
        SELECT fiscal_year, replace(account_nm, ' ', '') AS acct, json_agg(amount) AS amounts
        FROM core.financial_fact
        WHERE company_id = %(cid)s AND report_code = '11011' AND fs_div = 'CFS'
          AND replace(account_nm, ' ', '') IN ('영업활동현금흐름', '유형자산의취득', '배당금의지급',
                                               '자기주식의취득', '이자의지급')
        GROUP BY fiscal_year, replace(account_nm, ' ', '')) c),
    'mcap', (SELECT json_agg(json_build_object('d', qe.pe, 'v', (
                SELECT p.market_cap FROM core.price_daily p
                WHERE p.company_id = %(cid)s AND p.trade_date <= qe.pe AND p.market_cap IS NOT NULL
                ORDER BY p.trade_date DESC LIMIT 1)) ORDER BY qe.pe) FROM qe),
    'peers', (SELECT json_agg(x) FROM (
        SELECT c.market, c.ticker, c.name, t.op_margin_ttm, t.roe_ttm, t.per_ttm, t.pbr, t.debt_ratio
        FROM pg JOIN core.peer_member m USING (peer_group_id)
        JOIN core.company c ON c.company_id = m.company_id
        LEFT JOIN core.v_ttm t ON t.market = c.market AND t.ticker = c.ticker
        WHERE m.company_id <> %(cid)s) x),
    'peer_method', (SELECT g.method FROM core.peer_group g JOIN pg USING (peer_group_id)),
    'risk', (SELECT json_object_agg(feature, value) FROM core.feature_snapshot
             WHERE company_id = %(cid)s AND perspective = 'risk'
               AND as_of = (SELECT max(as_of) FROM core.feature_snapshot
                            WHERE company_id = %(cid)s AND as_of <= %(as_of)s::date))
) AS bundle
"""

SRC_TTM = "core.v_ttm (OpenDART TTM)"
SRC_Q = "core.financial_quarter (분기 단독값)"
SRC_CF = "core.financial_fact (사업보고서 현금흐름표, 연결)"


def params(co: dict, as_of: str) -> dict:
    return {"cid": co["company_id"], "ticker": co["ticker"], "as_of": as_of}


def _pct(x):
    return None if x is None else x * 100


def _quarters(b: dict) -> list[dict]:
    out = []
    for r in b.get("quarters") or []:
        m = r.get("m") or {}
        if m.get("revenue") is None and m.get("operating_income") is None:
            continue  # 재무상태표만 있는 분기
        out.append({"pe": str(r["period_end"])[:10], "fy": r["fiscal_year"], "fq": r["fiscal_q"],
                    "rev": m.get("revenue"), "op": m.get("operating_income"), "ni": m.get("net_income")})
    return out


def _year_before(pe: str) -> str:
    return f"{int(pe[:4]) - 1}{pe[4:]}"


def _days(a: str, b: str) -> int:
    from datetime import date

    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _consecutive(win: list[dict]) -> bool:
    """분기 묶음이 빠진 분기 없이 이어지는지 (첫 분기말과 마지막 분기말이 약 9개월 차이)."""
    from datetime import date

    span = (date.fromisoformat(win[-1]["pe"]) - date.fromisoformat(win[0]["pe"])).days
    return 250 <= span <= 300


def _cash(b: dict) -> dict[int, dict[str, float]]:
    """연도별 현금흐름 계정. 유출 계정은 부호가 섞여 있어 절댓값, 영업현금흐름은 절댓값이 가장 큰 값을 부호째."""
    out: dict[int, dict[str, float]] = {}
    for r in b.get("cash") or []:
        vals = [float(a) for a in (r.get("amounts") or []) if a is not None]
        if not vals:
            continue
        acct = r["acct"]
        v = max(vals, key=abs) if acct == "영업활동현금흐름" else max(abs(a) for a in vals)
        out.setdefault(int(r["fiscal_year"]), {})[acct] = v
    return out


def compute(b: dict, co: dict, as_of: str) -> dict:
    f = Facts("F")
    t = b.get("ttm") or {}
    is_fin = sector_of(co) in FINANCIAL_SECTORS
    from .agents import today_kst

    if as_of < today_kst():
        f.note("과거 기준일 실행: TTM·Peer·연간 PER은 최신 값이라 기준일 시점과 다를 수 있음 (분기 추세·PER 밴드는 기준일까지)")
    if is_fin:
        f.note("금융업: 매출·영업이익률·부채비율은 일반 기업과 의미가 달라 비교에 쓰지 않음. ROE·PBR 중심으로 해석")

    # 1) TTM
    if not t:
        f.gap("TTM 실적·멀티플", "core.v_ttm 에 이 종목 없음 (DART 재무 미수집 종목)")
    else:
        g = "TTM 실적"
        f.add("매출(TTM)", t.get("revenue_ttm"), "KRW", t.get("ttm_end"), SRC_TTM, group=g)
        f.add("영업이익(TTM)", t.get("operating_income_ttm"), "KRW", t.get("ttm_end"), SRC_TTM, group=g)
        k_ni = f.add("순이익(TTM)", t.get("net_income_ttm"), "KRW", t.get("ttm_end"), SRC_TTM, group=g)
        f.add("영업이익률(TTM)", _pct(t.get("op_margin_ttm")), "%", t.get("ttm_end"), SRC_TTM, kind="calc", group=g)
        f.add("ROE(TTM)", _pct(t.get("roe_ttm")), "%", t.get("ttm_end"), SRC_TTM, kind="calc", group=g)
        k_dr = f.add("부채비율", _pct(t.get("debt_ratio")), "%", t.get("bs_end"), SRC_TTM, kind="calc", group=g)
        f.add("PER(TTM 기준)", t.get("per_ttm"), "배", t.get("ttm_end"), SRC_TTM, kind="calc", group="밸류에이션",
              note="최근 4개 분기 순이익 기준")
        f.add("PBR", t.get("pbr"), "배", t.get("bs_end"), SRC_TTM, kind="calc", group="밸류에이션")
        if t.get("net_income_ttm") is not None and t["net_income_ttm"] < 0 and k_ni:
            f.flag(f"경고: TTM 순손실 ({{{k_ni}}}) → PER 해석 불가")
        if t.get("equity") is not None and t["equity"] <= 0:
            k = f.add("자본총계", t["equity"], "KRW", t.get("bs_end"), SRC_TTM, group=g)
            f.flag(f"경고: 완전자본잠식 ({{{k}}})")
        if t.get("debt_ratio") is not None and t["debt_ratio"] > 2 and k_dr and not is_fin:
            f.flag(f"경고: 부채비율 과다 ({{{k_dr}}}, 경고 기준 초과)")

    val = b.get("valuation") or {}
    if val.get("per") is not None:
        f.add(f"PER(연간 FY{val['fiscal_year']} 기준)", val["per"], "배", val.get("price_date"), "core.v_valuation",
              kind="calc", group="밸류에이션",
              note=f"주가 {val.get('price_date')} ÷ FY{val['fiscal_year']} 순이익. TTM PER과 기준이 다름")

    # 2) 분기 추세
    qs = _quarters(b)
    g = "분기 추세"
    by_pe = {q["pe"]: q for q in qs}
    if len(qs) >= 2 and _year_before(qs[-1]["pe"]) in by_pe:
        now, prev_y, prev_q = qs[-1], by_pe[_year_before(qs[-1]["pe"])], qs[-2]
        lab = f"{now['fy']}년 {now['fq']}분기"
        f.add(f"{lab} 매출", now["rev"], "KRW", now["pe"], SRC_Q, group=g)
        f.add(f"{lab} 영업이익", now["op"], "KRW", now["pe"], SRC_Q, group=g)
        f.add(f"{lab} 매출 전년 동기 대비", pct_change(now["rev"], prev_y["rev"]), "%chg", now["pe"], SRC_Q,
              kind="calc", group=g)
        k_opy = f.add(f"{lab} 영업이익 전년 동기 대비", pct_change(now["op"], prev_y["op"]), "%chg", now["pe"], SRC_Q,
                      kind="calc", group=g, note="전년 영업이익이 적자면 계산하지 않음")
        if k_opy is None and prev_y["op"] is not None and prev_y["op"] < 0 and (now["op"] or 0) > 0:
            f.flag(f"{lab} 영업이익 흑자 전환 (전년 동기 적자)")
        f.add(f"{lab} 매출 전 분기 대비", pct_change(now["rev"], prev_q["rev"]), "%chg", now["pe"], SRC_Q,
              kind="calc", group=g)
        margins = [(q["pe"], q["op"] / q["rev"] * 100) for q in qs[-5:] if q["rev"] and q["op"] is not None]
        if len(margins) >= 2:
            f.add(f"{lab} 영업이익률", margins[-1][1], "%", now["pe"], SRC_Q, kind="calc", group=g)
            m_prev_y = (prev_y["op"] / prev_y["rev"] * 100) if prev_y["rev"] and prev_y["op"] is not None else None
            if m_prev_y is not None:
                f.add(f"{lab} 영업이익률 전년 동기 대비 변화", margins[-1][1] - m_prev_y, "%p", now["pe"], SRC_Q,
                      kind="calc", group=g)
            last4 = [m for _, m in margins[-4:]]
            ups = sum(1 for a, b2 in pairwise(last4) if b2 > a)
            f.add("최근 4개 분기 중 영업이익률이 전 분기보다 오른 횟수", ups, "개", now["pe"], SRC_Q, kind="calc", group=g)
        run, later = 0, None
        for q in reversed(qs):
            base = by_pe.get(_year_before(q["pe"]))
            gap_ok = later is None or 80 <= _days(q["pe"], later["pe"]) <= 100  # 바로 앞 분기인지
            if gap_ok and base and q["rev"] is not None and base["rev"] is not None and q["rev"] > base["rev"]:
                run, later = run + 1, q
            else:
                break
        f.add("매출 전년 동기 대비 연속 증가 분기 수", run, "개", now["pe"], SRC_Q, kind="calc", group=g)
        if len(qs) >= 8 and all(q["rev"] is not None for q in qs[-8:]) and _consecutive(qs[-8:-4]) \
                and _consecutive(qs[-4:]) and qs[-4]["pe"] == f"{int(qs[-8]['pe'][:4]) + 1}{qs[-8]['pe'][4:]}":
            cur4, prev4 = sum(q["rev"] for q in qs[-4:]), sum(q["rev"] for q in qs[-8:-4])
            f.add("TTM 매출 전년 대비", pct_change(cur4, prev4), "%chg", now["pe"], SRC_Q, kind="calc", group=g)
        # 데이터 정합성: 최근 4개 분기 합계 ↔ v_ttm
        if t.get("revenue_ttm") and len(qs) >= 4 and _consecutive(qs[-4:]) \
                and all(q["rev"] is not None for q in qs[-4:]) and str(t.get("ttm_end"))[:10] == now["pe"]:
            diff = pct_change(sum(q["rev"] for q in qs[-4:]), t["revenue_ttm"])
            if diff is not None and abs(diff) > 1:
                f.flag("데이터 점검: 최근 4개 분기 매출 합계와 TTM 매출이 허용 오차 이상 다름 (수집 데이터 확인 필요)")
    else:
        f.gap("분기 추세", "최근 분기와 전년 같은 분기의 손익이 함께 있지 않음")

    # 3) 자기 PER 밴드 (분기말 시가총액 ÷ TTM 순이익)
    mcap = {str(r["d"])[:10]: r["v"] for r in (b.get("mcap") or []) if r.get("v") is not None}
    band = []
    for i in range(3, len(qs)):
        win = qs[i - 3:i + 1]
        if any(q["ni"] is None for q in win) or not _consecutive(win):
            continue
        ni = sum(q["ni"] for q in win)
        mc = mcap.get(qs[i]["pe"])
        if mc and ni > 0:
            band.append((qs[i]["pe"], mc / ni))
    cur_mc = mcap.get(as_of)
    if band and cur_mc and len(qs) >= 4 and _consecutive(qs[-4:]) and all(q["ni"] is not None for q in qs[-4:]):
        ni_now = sum(q["ni"] for q in qs[-4:])
        if ni_now > 0:
            cur = cur_mc / ni_now
            g = "밸류에이션"
            vals = [p for _, p in band]
            f.add("PER 밴드 현재값(시가총액 ÷ 최근 TTM 순이익)", cur, "배", as_of, "core.price_daily ÷ financial_quarter",
                  kind="calc", group=g)
            f.add(f"PER 밴드 최저(분기말 {len(band)}개)", min(vals), "배", f"{band[0][0]}~{band[-1][0]}",
                  "core.price_daily ÷ financial_quarter", kind="calc", group=g)
            f.add(f"PER 밴드 최고(분기말 {len(band)}개)", max(vals), "배", f"{band[0][0]}~{band[-1][0]}",
                  "core.price_daily ÷ financial_quarter", kind="calc", group=g)
            pr = percentile_rank(vals, cur)
            if pr is not None:
                f.add("현재 PER의 자기 밴드 내 위치", pr, "pctile", as_of, "core.price_daily ÷ financial_quarter",
                      kind="calc", group=g, note=f"분기말 {len(band)}개 중 위치. 표본이 짧아 참고용")
            else:
                f.gap("현재 PER의 자기 밴드 내 위치", f"분기말 PER {len(band)}개뿐 (5개 이상 필요)")
    else:
        f.gap("자기 PER 밴드", "분기 순이익 또는 분기말 시가총액 부족")

    # 4) Peer 비교
    peers = [p for p in (b.get("peers") or []) if p.get("op_margin_ttm") is not None]
    if len(peers) >= 3 and t:
        g = "Peer 비교"
        n_us = sum(1 for p in peers if p["market"] == "US")
        src = f"core.peer_member × v_ttm ({b.get('peer_method') or 'peer'})"
        note = f"Peer {len(peers)}개 (해외 {n_us}개 포함, 비율 지표라 통화 무관)"
        for label, col, mine, unit, scale in (
            ("영업이익률", "op_margin_ttm", t.get("op_margin_ttm"), "%", 100),
            ("ROE", "roe_ttm", t.get("roe_ttm"), "%", 100),
            ("PER(TTM)", "per_ttm", t.get("per_ttm"), "배", 1),
            ("PBR", "pbr", t.get("pbr"), "배", 1),
        ):
            vals = [p[col] for p in peers if p.get(col) is not None and (col != "per_ttm" or p[col] > 0)]
            med = median(vals)
            f.add(f"Peer {label} 중앙값", None if med is None else med * scale, unit, None, src, kind="calc", group=g,
                  note=note if label == "영업이익률" else "")
            if mine is not None and (col != "per_ttm" or mine > 0):
                pr = percentile_rank(vals, mine)
                f.add(f"{label}의 Peer 내 위치", pr, "pctile", None, src, kind="calc", group=g,
                      note="높을수록 Peer보다 값이 큼 (PER·PBR은 비쌈, 이익률·ROE는 우수)")
        ranked = sorted(peers, key=lambda p: p["op_margin_ttm"], reverse=True)
        f.note("Peer 영업이익률 상위: " + ", ".join(p["name"] for p in ranked[:3])
               + " / 하위: " + ", ".join(p["name"] for p in ranked[-3:]))
    else:
        f.gap("Peer 비교", "Peer 그룹 없음 또는 TTM 있는 Peer 3개 미만")

    # 5) 현금흐름(연간)과 이자 감당력
    cash = _cash(b)
    annual = {int(a["fiscal_year"]): a for a in (b.get("annual") or [])}
    years = sorted(y for y in cash if "영업활동현금흐름" in cash[y])
    g = "현금흐름(연간)"
    if years:
        y = years[-1]
        c = cash[y]
        ocf, capex = c.get("영업활동현금흐름"), c.get("유형자산의취득")
        k_ocf = f.add(f"FY{y} 영업현금흐름", ocf, "KRW", f"FY{y}", SRC_CF, group=g)
        f.add(f"FY{y} 설비투자(유형자산 취득)", capex, "KRW", f"FY{y}", SRC_CF, group=g)
        fcf = None if ocf is None or capex is None else ocf - capex
        k_fcf = f.add(f"FY{y} 잉여현금흐름(FCF)", fcf, "KRW", f"FY{y}", SRC_CF, kind="calc", group=g,
                      note="영업현금흐름 − 유형자산 취득 (무형자산 투자 제외)")
        ret = (c.get("배당금의지급") or 0) + (c.get("자기주식의취득") or 0)
        k_ret = f.add(f"FY{y} 주주환원(배당 + 자사주 취득)", ret or None, "KRW", f"FY{y}", SRC_CF, group=g)
        if fcf and fcf > 0 and ret:
            f.add(f"FY{y} 주주환원 ÷ FCF", ret / fcf * 100, "%", f"FY{y}", SRC_CF, kind="calc", group=g)
        if ocf is not None and ocf < 0 and k_ocf:
            f.flag(f"경고: 영업현금흐름 적자 ({{{k_ocf}}})")
        if fcf is not None and fcf < 0 and k_fcf:
            f.flag(f"주의: 잉여현금흐름 적자 ({{{k_fcf}}}) — 설비투자 확대기일 수 있음"
                   + (f", 주주환원 {{{k_ret}}}은 FCF를 넘음" if k_ret else ""))
        last3 = [yy for yy in years[-3:] if "유형자산의취득" in cash[yy]]
        if len(last3) == 3:
            s = sum(cash[yy]["영업활동현금흐름"] - cash[yy]["유형자산의취득"] for yy in last3)
            f.add(f"FCF 3년 합계(FY{last3[0]}~FY{last3[-1]})", s, "KRW", f"FY{last3[-1]}", SRC_CF, kind="calc", group=g)
        ip = c.get("이자의지급")
        op = (annual.get(y) or {}).get("operating_income")
        if ip and op is not None:
            k = f.add(f"이자보상배율 대용치(FY{y})", op / ip, "배", f"FY{y}", "v_fundamentals_annual ÷ 이자의 지급",
                      kind="proxy", group=g, note="영업이익 ÷ 현금흐름표 이자 지급액 (손익계산서 이자비용 아님)")
            if op / ip < 1 and k:
                f.flag(f"경고: 이자보상배율 대용치 1 미만 ({{{k}}})")
        else:
            f.gap("이자보상배율", "사업보고서 '이자의 지급' 계정 또는 연간 영업이익 없음")
    else:
        f.gap("현금흐름(연간)", "사업보고서 현금흐름표 미수집")

    # 6) 가격 위험
    risk = b.get("risk") or {}
    for feat, label in (("max_drawdown_250d", "최근 250일 최대 낙폭"), ("volatility_60d", "60일 변동성(연율)"),
                        ("below_52w_high", "52주 고점 대비")):
        v = risk.get(feat)
        f.add(label, None if v is None else v * 100, "%", None, "core.feature_snapshot", kind="calc", group="가격 위험")
    for label, reason in (("EV/EBITDA", "감가상각비·순차입금 미수집"), ("감사의견", "미수집"),
                          ("순차입금", "현금성자산·차입금 계정 미수집")):
        f.gap(label, reason)
    period = (f"TTM {t.get('ttm_end')}" if t else "TTM 없음") + (f" · 분기 {qs[0]['pe']}~{qs[-1]['pe']}" if qs else "")
    return {"facts": f, "docs": [], "period": period}
