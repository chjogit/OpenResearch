"""#55 적중률 측정: as_of 규칙(미래 데이터 금지)·적중 정의·표본·기준선·신뢰구간·결과 파일 형식. 모의 입력, DB 없음."""
import json
from pathlib import Path

from ch_agents import outlook
from outlook import backtest as bt


def flows(n=80):
    """오래된 날짜 → 최신 순서(오름차순) 수급 행. 외국인이 매일 같은 크기로 순매수(강도가 +로 큼)."""
    return [{"d": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "fq": 1000, "iq": 0, "pq": -1000, "close": 100.0, "tv": 20000.0} for i in range(n)]


def test_flow_items_use_only_rows_up_to_t():
    rows = flows()
    dates = [r["d"] for r in rows]
    t = dates[60]
    base = bt.flow_items(rows, dates, t)
    poisoned = rows + [{"d": "2030-01-01", "fq": -10**9, "iq": -10**9, "pq": 0, "close": 100.0, "tv": 1.0}]
    assert bt.flow_items(poisoned, dates + ["2030-01-01"], t) == base                          # t 이후 행을 넣어도 같은 값 (as_of 규칙)
    changed = [dict(r, fq=-10**6) if r["d"] > t else r for r in rows]
    assert bt.flow_items(changed, dates, t) == base
    r = outlook.compute(4, base, t)
    assert r["direction"] == "positive" and r["startAfter"] == t


def test_forward_uses_close_at_t_and_20_days_later_with_kospi_excess():
    px = [(f"d{i:03d}", 100.0 + i) for i in range(60)]
    kospi = {d: 1000.0 + 2 * i for i, (d, _) in enumerate(px)}
    fw = bt.forward(px, kospi, 30)
    assert abs(fw["ret"] - (150 / 130 - 1)) < 1e-12 and abs(fw["kospi"] - (1100 / 1060 - 1)) < 1e-12
    assert abs(fw["excess"] - (fw["ret"] - fw["kospi"])) < 1e-12 and fw["end"] == "d050"
    assert bt.forward(px, kospi, 45) is None and bt.forward(px, kospi, 5) is None                # 이후 20거래일 또는 직전 20거래일이 모자라면 표본 아님


def rows(spec):
    return [{"agent": 4, "ticker": "T", "asOf": f"d{i}", "direction": d, "reason": "", "idx": i * 20, "end": "e", "ret": r, "kospi": 0.0, "excess": x, "prevExcess": p}
            for i, (d, r, x, p) in enumerate(spec)]


def test_hit_definition_neutral_excluded_and_baselines():
    s = bt.summarize(rows([("positive", 0.05, 0.02, 0.01),    # 적중
                           ("positive", 0.02, -0.01, 0.03),   # 초과수익률 음수 → 빗나감 (절대수익률은 적중)
                           ("negative", -0.03, -0.02, -0.01),  # 적중
                           ("negative", 0.01, 0.00, -0.02),    # 초과수익률 0 → 빗나감
                           ("neutral", 0.1, 0.1, 0.1)]))
    assert s["calls"] == 4 and s["neutral"] == 1 and s["neutralShare"] == 0.2
    assert (s["primary"]["hits"], s["primary"]["n"]) == (2, 4)
    assert (s["absolute"]["hits"], s["absolute"]["n"]) == (3, 4)                                 # 보조: 절대수익률
    assert s["baselines"]["alwaysPositive"]["hits"] == 1                                          # 비중립 4건 중 초과수익률>0 은 1건
    assert s["baselines"]["momentum"]["hits"] == 2                                                # 직전 초과수익률 부호가 이후와 같은 건: 첫째·셋째 (초과수익률 0 은 방향 없음)
    assert s["baselines"]["random"]["rate"] == 0.5


def test_wilson_interval_contains_rate_and_narrows_with_n():
    a, b = bt.wilson(50, 100), bt.wilson(500, 1000)
    assert a[0] < 0.5 < a[1] and b[0] < 0.5 < b[1] and (b[1] - b[0]) < (a[1] - a[0])
    assert bt.wilson(0, 0) is None and bt.wilson(10, 10)[1] == 1.0


def test_result_file_matches_reader_format_when_present():
    p = Path(bt.RESULT_JSON)
    if not p.exists():
        return
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["ruleVersion"] in (outlook.RULE_VERSION, *outlook.MEASURED_COMPATIBLE[4]) and doc["horizonDays"] == 20       # r1.1(#76)은 에이전트 6 창만 바뀜
    for no in ("3", "4"):
        h = outlook.hit_rate(int(no), p)
        e = doc["agents"][no]
        assert h["status"] in ("measured", "unverified")
        assert e["n"] == e["nonOverlapping"]["primary"]["n"] and e["allDays"]["primary"]["n"] >= e["n"]
        assert set(e["nonOverlapping"]["baselines"]) == {"alwaysPositive", "momentum", "random"}
    assert "14일" in outlook.hit_rate(6, p)["reason"]
