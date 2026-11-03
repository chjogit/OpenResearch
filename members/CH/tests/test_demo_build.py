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


def _opinion_runs():
    r = _run("005930", 6, True)
    r["contract"] = {"claims": [], "nodes": [], "evidence": [
        {"evidenceId": "E1", "kind": "document", "label": "카페 글 본문 조각이 여기 들어 있습니다...", "source": "naver_cafe", "url": "https://cafe.naver.com/x/1", "note": "메모"},
        {"evidenceId": "E2", "kind": "document", "label": "뉴스 기사 제목은 그대로 둡니다", "source": "naver_news", "url": "https://n.news.naver.com/1", "note": None}],
        "conflicts": [{"nodeId": "N11", "topic": "사건 E1 논조", "views": [
            {"text": "긍정 분류: 블로그 글 조각을 인용한 문장입니다 정말로", "tag": "Interpretation", "evidenceLinks": ["doc:11"]},
            {"text": "부정 분류: 뉴스 제목 인용은 그대로 둡니다 뉴스", "tag": "Interpretation", "evidenceLinks": ["doc:22"]},
            {"text": "부정 분류: 출처를 못 찾은 문서의 조각 문장입니다 글", "tag": "Interpretation", "evidenceLinks": ["doc:33"]}]}]}
    return {"as_of": "2026-10-30", "runs": {"005930|6|1": r}}


def test_mask_opinion_hides_blog_cafe_but_keeps_news_and_ids():
    runs = _opinion_runs()
    out, snippets = bd.mask_opinion(runs, {11: "naver_blog", 22: "naver_news"})
    c = out["runs"]["005930|6|1"]["contract"]
    e1, e2 = c["evidence"]
    assert e1["label"] == bd.HIDDEN and e1["url"] is None and e1["note"] is None and e1["source"] == "naver_cafe" and e1["evidenceId"] == "E1"
    assert e2["label"].startswith("뉴스 기사") and e2["url"]                          # 뉴스는 그대로
    v = c["conflicts"][0]["views"]
    assert v[0]["text"] == "긍정 분류: " + bd.HIDDEN and v[0]["evidenceLinks"] == ["doc:11"]
    assert v[1]["text"].endswith("그대로 둡니다 뉴스")                                  # 뉴스 인용 유지
    assert v[2]["text"] == "부정 분류: " + bd.HIDDEN                                   # 출처 못 찾으면 보수적으로 가림
    assert "cafe.naver.com" in json.dumps(runs) and "cafe.naver.com" not in json.dumps(out, ensure_ascii=False)
    html = json.dumps(out, ensure_ascii=False)
    assert bd.opinion_leaks(html, snippets) == []


def test_opinion_leaks_detects_remaining_snippet_or_domain():
    assert bd.opinion_leaks("ok https://blog.naver.com/a", [])
    assert bd.opinion_leaks("본문 카페 글 본문 조각이 여기", ["카페 글 본문 조각이 여기"])
    assert bd.opinion_leaks("깨끗", ["카페 글 본문 조각이 여기"]) == []


def test_conflict_doc_ids_collects_doc_links():
    assert bd.conflict_doc_ids(_opinion_runs()) == [11, 22, 33]


def _kr_runs():
    r = _run("005930", 6, True)
    r["contract"] = {"claims": [], "evidence": [{"evidenceId": "E1", "kind": "document", "label": "현대차 3.6%↓…목표주가 줄하향", "source": "naver_news"}],
                     "nodes": [{"nodeId": "N12", "state": "skipped", "reason": "확장 노드 입력 요건 미충족", "missingInputs": ["price_after_event", "scenario_assumptions", "호가 잔량"]}],
                     "unverified": [{"item": "price_after_event 기반 후속 반응이 수행되지 않음", "reason": "x"}], "nextChecks": ["충족 시 price_after_event 기반 확인"],
                     "conflicts": [{"views": [{"text": "긍정 분류: 목표가 상향 소식 뉴스", "evidenceLinks": []}]}]}
    r["render"] = {lv: "정상 문장" for lv in bd.LEVELS}
    return {"as_of": "2026-10-30", "runs": {"005930|6|1": r}}


def test_localize_missing_replaces_internal_keys_with_korean():
    runs = _kr_runs()
    assert bd.raw_key_hits(runs) == ["price_after_event", "scenario_assumptions"] or "price_after_event" in bd.raw_key_hits(runs)
    out = bd.localize_missing(runs)
    c = out["runs"]["005930|6|1"]["contract"]
    assert c["nodes"][0]["missingInputs"] == [bd.MISSING_KO["price_after_event"], bd.MISSING_KO["scenario_assumptions"], "호가 잔량(공개 원천 없음)"]
    assert "사건 이후 주가 기반 후속 반응" in c["unverified"][0]["item"]
    assert "사건 이후 주가 기반 확인" in c["nextChecks"][0] and bd.raw_key_hits(out) == []


def test_raw_key_hits_flags_unmapped_key():
    runs = _kr_runs()
    runs["runs"]["005930|6|1"]["contract"]["nodes"][0]["missingInputs"].append("some_new_key")
    assert "some_new_key" in bd.raw_key_hits(bd.localize_missing(runs))


def test_mask_target_price_only_in_quotes():
    out = bd.mask_target_price(_kr_runs())
    c = out["runs"]["005930|6|1"]["contract"]
    assert c["evidence"][0]["label"] == "현대차 3.6%↓…[증권사 가격 전망] 줄하향"
    assert c["conflicts"][0]["views"][0]["text"] == "긍정 분류: [증권사 가격 전망] 상향 소식 뉴스"
    assert not bd.TARGET_PRICE.search(json.dumps(out, ensure_ascii=False))


def test_youtube_comments_are_masked_like_blog_cafe():
    runs = _opinion_runs()
    runs["runs"]["005930|6|1"]["contract"]["evidence"].append(
        {"evidenceId": "E9", "kind": "document", "label": "유튜브 댓글 조각이 들어 있는 근거 문장입니다", "source": "youtube_comment", "url": "https://www.youtube.com/watch?v=x", "note": "m"})
    out, snippets = bd.mask_opinion(runs, {11: "youtube_comment", 22: "naver_news", 33: "naver_news"})
    c = out["runs"]["005930|6|1"]["contract"]
    assert c["evidence"][2]["label"] == bd.HIDDEN and c["evidence"][2]["url"] is None
    assert c["conflicts"][0]["views"][0]["text"].endswith(bd.HIDDEN) and "뉴스 제목 인용" in c["conflicts"][0]["views"][1]["text"]
    assert bd.opinion_leaks(json.dumps(out, ensure_ascii=False), snippets) == []
    assert bd.opinion_leaks("https://www.youtube.com/watch?v=x", [])
