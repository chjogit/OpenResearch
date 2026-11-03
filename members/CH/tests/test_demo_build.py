"""#41 시연 HTML 생성 스크립트 시험 (DB·LLM 없이)."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("build_demo", Path(__file__).resolve().parents[1] / "demo" / "build_demo.py")
bd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bd)


def _run(ticker="005930", agent=3, ext=False):
    return {"ticker": ticker, "name": "삼성전자", "agentNo": agent, "agentName": bd.AGENTS[agent], "ext": ext, "status": "완료",
            "seconds": 3.0, "attempts": 2, "removed": 1, "claims": 1,
            "contract": {"claims": [{"claimId": "C01", "text": "x</script><b>", "evidenceIds": ["E1"]}], "nodes": [], "evidence": []},
            "render": {lv: "### 제목\n\n**굵게**" for lv in bd.LEVELS}}


def _runs():
    return {"as_of": "2026-10-30", "runs": {bd.key_of(t, a, e): _run(t, a, e) for t, _ in bd.TICKERS for a in bd.AGENTS for e in (False, True)}}


def _status():
    return {"main": {"mb": 633, "docs": []}, "opinion": {"mb": 239, "docs": []}, "tables": [], "unavailable": ["x"], "limits": {"main_mb": 800, "retention_days": 14}}


def test_cut_truncates_long_strings_recursively():
    out = bd._cut({"a": "가" * 1000, "b": ["짧음", {"c": "나" * 500}]})
    assert len(out["a"]) == bd.MAX_STR + 1 and out["b"][0] == "짧음" and len(out["b"][1]["c"]) == bd.MAX_STR + 1


def test_payload_counts_runs_and_llm_calls():
    p = bd.build_payload(_runs(), _status(), generated_at="t")
    assert p["meta"]["runs"] == 24 and p["meta"]["llmCalls"] == 48 and p["meta"]["asOf"] == "2026-10-30"
    assert [t["ticker"] for t in p["tickers"]][:3] == ["005930", "000660", "005380"]


def test_html_embeds_valid_json_and_escapes_script_end():
    html = bd.build_html(bd.build_payload(_runs(), _status(), generated_at="t"))
    blob = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S).group(1)
    data = json.loads(blob)                                       # 본문의 </script> 가 JSON 을 끊지 않음
    assert data["runs"]["005930|3|0"]["contract"]["claims"][0]["text"].startswith("x</script>")
    assert "<title>" in html and "viewport" in html
    assert not re.search(r'(src|href)="https?://', html.replace("rel=\"noopener", ""))      # 외부 리소스 없음


def test_forbidden_hits_catches_secrets_and_urls():
    assert bd.forbidden_hits("정상 문장") == []
    assert bd.forbidden_hits("postgresql://u:p@host/db")
    assert bd.forbidden_hits("UPSTAGE_API_KEY=abc")
    assert bd.forbidden_hits("값 supersecretvalue123 포함", secrets=["supersecretvalue123"])
    assert bd.forbidden_hits("값 짧음", secrets=["abc"]) == []                       # 8자 미만은 무시


def test_collect_runs_resumes_from_cache_and_runs_missing_only(tmp_path):
    cache = tmp_path / "runs.json"
    first = {"as_of": "2026-10-30", "runs": {bd.key_of("005930", 3, False): _run()}}
    cache.write_text(json.dumps(first, ensure_ascii=False), encoding="utf-8")
    calls = []

    def fake(as_of, t, n, a, e):
        calls.append((t, a, e))
        return _run(t, a, e)

    out = bd.collect_runs("2026-10-30", workers=2, cache=cache, runner=fake)
    assert len(out["runs"]) == 24 and len(calls) == 23 and ("005930", 3, False) not in calls
    assert len(json.loads(cache.read_text(encoding="utf-8"))["runs"]) == 24
    calls.clear()
    bd.collect_runs("2026-10-30", workers=2, cache=cache, runner=fake)
    assert calls == []                                                               # 다 있으면 호출 0


def test_collect_runs_discards_cache_for_other_as_of(tmp_path):
    cache = tmp_path / "runs.json"
    cache.write_text(json.dumps({"as_of": "2026-10-01", "runs": {"x": {}}}), encoding="utf-8")
    out = bd.collect_runs("2026-10-30", workers=2, cache=cache, runner=lambda a, t, n, ag, e: _run(t, ag, e))
    assert "x" not in out["runs"] and len(out["runs"]) == 24


def test_template_has_four_sections_and_level_switch():
    t = (Path(bd.HERE) / "template.html").read_text(encoding="utf-8")
    for token in ("1 개요", "2 에이전트 시연", "3 데이터 현황", "4 검증 기록", "L1 입문", "L2 일반", "L3 전문", "확장 노드", "overflow-x:auto"):
        assert token in t
