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
    for token in ("1 질문하고 답 보기", "2 성능", "3 구조·데이터", "4 저장된 4종목 결과", "L1 입문", "L2 일반", "L3 전문", "확장 노드", "overflow-x:auto"):
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


def test_payload_has_sentiment_eval_and_commit_and_template_renders_it():
    p = bd.build_payload(_runs(), _status())
    e = p["sentimentEval"]
    assert e["n_labeled"] == 600 and e["n_scored"] == 440 and e["accuracy"] == 56.6
    assert set(e["per_class"]) == {"긍정", "중립", "부정"} and len(e["by_source"]) == 5
    assert "commit" in p["meta"]
    tpl = (Path(bd.HERE) / "template.html").read_text(encoding="utf-8")
    assert "sentEval()" in tpl and "SW 검수 후 라벨 일치도" in tpl and "기준 커밋" in tpl and "시장 지표" in tpl
    assert "검증 통과" not in tpl.replace("검증 통과가 아니라", "")


def test_unavailable_list_no_longer_says_credit_or_sentiment_pending():
    assert not any("신용공여" in x or "라벨링 진행 중" in x for x in bd.UNAVAILABLE)
    assert "core.credit_balance" in [t for t, _ in bd.TABLES]


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


# ---- #48 표시 정리
def test_ko_text_translates_internal_codes_even_before_korean_particles():
    out = bd.ko_text("사건 E1과 E9는 N05 미충족 항목, E10에서 CAR 와 D1 사후 탐색 등급, 확장 노드 입력 요건 미충족")
    assert "사건 1과 9는" in out and "거시 데이터 점검" in out and "근거 10에서" in out
    assert "사건 뒤 주가 반응(초과수익)" in out and "사후 탐색 단계(검증 전)" in out and "추가 분석에 필요한 자료 부족" in out
    assert not bd.RAW_CODE_RE.search(out)


def _conflict(text_a, text_b):
    return {"nodeId": "N11", "topic": "사건 E1 논조", "views": [
        {"text": text_a, "tag": "Interpretation", "evidenceLinks": ["doc:11"]}, {"text": text_b, "tag": "Interpretation", "evidenceLinks": ["doc:22"]}]}


def test_conflict_card_summarises_when_both_views_hidden_and_tables_otherwise():
    hid = bd.conflict_card(_conflict(f"긍정 분류: {bd.HIDDEN}", f"부정 분류: {bd.HIDDEN}"))
    assert hid["views"] == [] and "긍정 1건·부정 1건" in hid["summary"] and "내용 비공개" in hid["summary"] and "11, 22" in hid["summary"]
    vis = bd.conflict_card(_conflict("긍정 분류: 실적 개선", "부정 분류: 소송 우려"))
    assert vis["summary"] is None and vis["views"][0]["tagKo"] == "해석" and vis["views"][1]["docs"] == ["22"]


def test_split_stat_drops_zero_clauses_and_keeps_nonzero():
    rest, proc = bd.split_stat("근거 문장을 붙이지 못해 점수를 내지 않은 문서 0건, 대상 기업 아님으로 분리한 문서 43건")
    assert rest == "" and proc == ["대상 기업 아님으로 분리한 문서 43건"]
    assert bd.split_stat("블로그 감성 변화") == ("블로그 감성 변화", [])


def test_localize_moves_stats_out_of_unverified_and_display_hits_is_clean():
    stat = "근거 문장을 붙이지 못해 점수를 내지 않은 문서 0건, 대상 기업 아님으로 분리한 문서 43건"
    run = _run(agent=6, ext=True)
    run["contract"].update({"unverified": [{"item": stat, "reason": "N11 미충족 항목"}, {"item": "블로그 감성 변화", "reason": "직전 기간 부족"}],
                            "conflicts": [_conflict(f"긍정 분류: {bd.HIDDEN}", f"부정 분류: {bd.HIDDEN}")],
                            "nodes": [{"nodeId": "N11", "name": "Sentiment_Base", "missingInputs": [stat], "reason": "확장 노드 입력 요건 미충족"}]})
    out = bd.localize({"as_of": "x", "runs": {"k": run}})["runs"]["k"]
    c = out["contract"]
    assert [u["item"] for u in c["unverified"]] == ["블로그 감성 변화"] and c["processing"] == ["대상 기업 아님으로 분리한 문서 43건"]
    assert c["nodes"][0]["missingInputs"] == [] and c["nodes"][0]["nodeId"] == "N11"      # 식별자 칸은 그대로
    assert c["conflicts"][0]["topic"] == "사건 1 논조" and not bd.display_hits({"runs": {"k": out}})


def test_display_hits_catches_json_raw_code_and_zero_items():
    run = _run()
    run["contract"]["summary"] = '{"nodeId":"N11"}'
    run["contract"]["unverified"] = [{"item": "문서 0건 처리"}]
    run["render"]["L1"] = "N05 점검"
    hits = bd.display_hits({"runs": {"k": run}})
    assert any("JSON" in h for h in hits) and any("내부 코드" in h for h in hits) and any("0건" in h for h in hits)


def _ol_block(direction="neutral", text="x"):
    return {"direction": direction, "directionLabel": "중립", "positiveFactors": [], "negativeFactors": [], "signals": [{"text": text}], "limit": "한계", "note": "참고"}


def test_collect_outlook_covers_all_tickers_agents_and_uses_contract_block(monkeypatch):
    from ch_agents import contract

    monkeypatch.setattr(contract, "outlook_block", lambda ol, _c: _ol_block(text=ol["t"]))
    out = bd.collect_outlook("2026-10-30", builder=lambda as_of, t, no: {"t": f"{t}-{no}"})
    assert set(out) == {t for t, _ in bd.TICKERS} and all(set(v) == {"3", "4", "6"} for v in out.values())


def test_collect_outlook_rejects_advice_text(monkeypatch):
    from ch_agents import contract

    monkeypatch.setattr(contract, "outlook_block", lambda ol, _c: _ol_block(text="지금이 매수 적기"))
    with pytest.raises(ValueError):
        bd.collect_outlook("2026-10-30", builder=lambda *a: {})


def test_payload_and_template_carry_outlook_and_r41_and_validation():
    p = bd.build_payload(_runs(), _status(), outlook={"005930": {"4": _ol_block()}})
    assert p["meta"]["contract"] == "r4-1.4" and p["outlook"]["005930"]["4"]["direction"] == "neutral" and "outlookNote" in p["meta"]
    v = p["outlookValidation"]
    assert v["status"] in ("measured", "none")
    if v["status"] == "measured":
        by = {r["agent"]: r for r in v["rows"]}
        assert "unverified" in by[6] and by[4]["baselines"]["random"] == 0.5 and by[4]["ci95"]
    tpl = (Path(bd.HERE) / "template.html").read_text(encoding="utf-8")
    assert "outlookBlock()" in tpl and "outlookValid()" in tpl and "오케스트레이터(SW) 담당" in tpl


def test_outlook_validation_none_without_results_file(monkeypatch, tmp_path):
    monkeypatch.setattr(bd, "HERE", tmp_path / "demo")
    assert bd.load_outlook_validation()["status"] == "none"


# ---- #59 시연 HTML 하나 (질문 → 에이전트 작동 → 답)

def _q_item(typ="수급", sentences=None, intent="현황", removed=None):
    ans = sentences or [{"문장": "외국인 순매수는 {S1}이다.", "구분": "사실", "방향": "중립", "근거": ["S1"]}]
    return {"type": typ, "question": "삼성전자 수급?", "result": {
        "answer": ans, "evidence": {"장부": {"S1": {"항목": "x", "값": "1", "기준일": "d", "출처": "s"}}, "문서": {}},
        "interpretation": {"intent": intent}, "trace": [{"kind": "답·검사", "removed": removed or []}], "usage": {"llm_calls": 1}}}


def test_question_problems_flags_conclusions_urls_and_missing_notice():
    from qa import agent

    assert bd.question_problems([_q_item()]) == []
    assert bd.question_problems([_q_item(sentences=[{"문장": "지금 사세요", "구분": "해석", "방향": "긍정", "근거": []}])])
    assert bd.question_problems([_q_item(sentences=[{"문장": "목표주가 상향", "구분": "해석", "방향": "긍정", "근거": []}])])
    judg = _q_item(intent="투자판단자료")
    notice = [{"문장": agent.JUDGMENT_NOTICE, "구분": "안내", "방향": "안내", "근거": []}]
    assert bd.question_problems([judg]) and bd.question_problems([{**judg, "result": {**judg["result"], "answer": notice}}]) == []
    bad = _q_item()
    bad["result"]["evidence"]["문서"] = {"D1": {"title": "t", "source": "s", "url": "https://blog.naver.com/x"}}
    assert bd.question_problems([bad])


def test_collect_questions_resumes_and_payload_embeds_them(tmp_path):
    calls = []

    def runner(q):
        calls.append(q)
        return {"answer": []}

    cache = tmp_path / "q.json"
    first = bd.collect_questions(cache, runner)
    assert [it["question"] for it in first["items"]] == [q for _, q in bd.QUESTIONS] and len(calls) == len(bd.QUESTIONS) >= 10
    assert {"수급", "거시", "심리·뉴스", "투자 판단", "데이터 없음", "거절"} <= {t for t, _ in bd.QUESTIONS}
    bd.collect_questions(cache, runner)
    assert len(calls) == len(bd.QUESTIONS)                       # 이어서 하기: 이미 있는 질문은 다시 실행하지 않음
    p = bd.build_payload(_runs(), _status(), questions=first)
    assert len(p["questions"]["items"]) == len(bd.QUESTIONS) and "interpEval" in p


def test_template_has_live_and_replay_flow_with_all_stages():
    t = (Path(bd.HERE) / "template.html").read_text(encoding="utf-8")
    for token in ("/api/status", "/api/ask", "실시간 모드 꺼짐", "저장된 기록 재생", "askReplay", "NodeTask", "ragBlock", "생성·검사 요약", "제거된 문장",
                  "data-k", "evl", "근거 (장부 값·문서)", "outlookCard", "오케스트레이터(SW) 담당", "python -m qa.eval_interp", "questions"):
        assert token in t, token
    assert "목표주가" not in t.replace("목표주가가 아닙니다", "")
