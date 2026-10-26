from agent.db import ToolResult
from agent.verifier.fact_source_verifier import verify


def _result(**row):
    return ToolResult(tool="t", source="Neon core", sql="", params={}, rows=[row])


def test_all_numbers_matched_adds_source_tag():
    r = _result(revenue_ttm=302231000000000, op_margin_ttm=0.1234, per_ttm=15.3)
    out = verify("2026년 3분기 TTM 매출은 302.2조원, 영업이익률 12.3%, PER 15.3배입니다.", [r])
    assert out.ok, out.unmatched
    assert out.text.endswith("[출처: Neon core]")


def test_unknown_number_is_flagged():
    r = _result(per_ttm=15.3)
    out = verify("PER 18.0배입니다.", [r])
    assert not out.ok
    assert out.unmatched == ["18.0배"]
