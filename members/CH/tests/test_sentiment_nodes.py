"""#23 투자심리·뉴스 에이전트(6): N11 감성·불확실성 / N12 후속 시장 반응 검증. 모의 입력, 네트워크·DB·LLM 없음."""
import copy
import random
import re
from datetime import date, timedelta

import pytest

from ch_agents import agent3_sentiment_flow as a3
from ch_agents import nodes, sentiment_nodes as sn
from conftest import AS_OF, CO, trading_days
from test_compute import _sent_bundle

D0 = date.fromisoformat(AS_OF)


def day(i):
    return (D0 - timedelta(days=i)).isoformat()


def doc(i, title="삼성전자 HBM 공급 확대 기대", summary="삼성전자가 HBM 공급을 늘린다고 밝혔다. 시장은 기대를 나타냈다.", score=0.5,
        label="positive", d=0, source="naver_news", chunk=None):
    return {"doc_id": i, "source": source, "title": title, "summary": summary, "url": f"https://x/{i}", "d": day(d),
            "score": score, "label": label, "method": "lexicon", "chunk_id": chunk}


def series(n=150, effect=0.0, seed=3):
    """n 거래일 일별 감성·시세. effect != 0 이면 다음 날 초과수익이 전일 감성 변화에 비례하도록 만든다(검증용)."""
    rng = random.Random(seed)
    days = trading_days(n)
    sent = [rng.uniform(-0.4, 0.4) for _ in days]
    price, kospi, p, k = [], [], 70000.0, 3000.0
    for i, d in enumerate(days):
        chg = sent[i - 1] - sent[i - 2] if i >= 2 else 0.0
        ret = effect * chg * 100 + rng.uniform(-0.05, 0.05) if effect else rng.uniform(-1, 1)
        p *= 1 + ret / 100
        price.append({"d": d, "v": p})
        kospi.append({"d": d, "v": k})
    return [{"d": d, "n": 5, "score": s} for d, s in zip(days, sent)], price, kospi


def inputs(docs=None, effect=0.0, n=150, **over):
    daily, price, kospi = series(n, effect)
    docs = docs if docs is not None else [doc(100 + i, d=i % 8, title=f"삼성전자 사건{i} 기대", chunk=900 + i) for i in range(6)]
    b = {"docs": docs, "grouped": [{"d": r["d"], "source": r["source"], "n": 1, "score": r["score"]} for r in docs],
         "daily": daily, "docs_agg": None, "price": price, "kospi": kospi, "search": [], "company": CO}
    b.update(over)
    return b


def run(ext=False, validated=False, **kw):
    return sn.run_sentiment_agent("005930", AS_OF, extension=ext, inputs=inputs(**kw), validated=validated)


# ---- N11: 근거 문장

def test_every_score_has_evidence_sentence_with_document_and_chunk_ids():
    res = run()["results"]["N11"]
    assert res.artifacts["events"]
    for ev in res.artifacts["events"]:
        assert ev["evidence"], ev
        for e in ev["evidence"]:
            assert e["doc_id"] and e["sentence"] and "삼성전자" in e["sentence"] and e["chunk_id"] is not None
    assert nodes.result_problems(res) == []
    scored = [f for f in res.findings if f.text.startswith("사건 E")]
    assert scored and all(any(l.startswith("doc:") for l in f.evidence_links) for f in scored)    # 점수 진술에 문서 ID 연결
    led = res.artifacts["ledger"]
    ids = {f"doc:{e['doc_id']}" for ev in res.artifacts["events"] for e in ev["evidence"]}
    assert all(l in led or l in ids for f in res.findings for l in f.evidence_links)


def test_score_without_evidence_sentence_is_not_emitted():
    bad = doc(500, title="업황 점검", summary="전반적인 흐름을 짚었다.")           # 기업 언급 없음 → 분리
    weak = doc(501, title="오늘의 증시", summary="삼성전자", score=0.9)           # 제목엔 없고 요약은 이름만 → 문장은 있음
    nodoc = doc(502, title="삼성전자", summary="", score=0.9)                      # 제목에만 → 제목이 근거 문장
    r = sn.n11(sn.clean_inputs(inputs(docs=[bad]), AS_OF), AS_OF)
    assert r.artifacts["events"] == [] and r.artifacts["separated_off_target"][0]["doc_id"] == 500
    assert not any(f.text.startswith("사건 E") for f in r.findings) and "근거 문장이 있는 대상 기업 기사" in " ".join(r.missing_items)
    r2 = sn.n11(sn.clean_inputs(inputs(docs=[weak, nodoc]), AS_OF), AS_OF)
    assert {e["doc_id"] for ev in r2.artifacts["events"] for e in ev["evidence"]} == {501, 502}


def test_unscored_documents_get_no_score():
    r = sn.n11(sn.clean_inputs(inputs(docs=[doc(1), doc(2, score=None, label="none")]), AS_OF), AS_OF)
    assert r.artifacts["n_unscored"] == 1
    assert [e["doc_id"] for ev in r.artifacts["events"] for e in ev["evidence"]] == [1]


def test_off_target_documents_are_separated_not_scored():
    other = doc(7, title="SK하이닉스 실적 기대", summary="SK하이닉스가 흑자를 냈다.", d=1)
    r = sn.n11(sn.clean_inputs(inputs(docs=[doc(1), other]), AS_OF), AS_OF)
    assert [x["doc_id"] for x in r.artifacts["separated_off_target"]] == [7]
    assert all(e["doc_id"] != 7 for ev in r.artifacts["events"] for e in ev["evidence"])
    assert any("대상 기업 아님으로 분리한 문서 1건" in m for m in r.missing_items)


# ---- N11: 사건 병합·불확실성·ambiguity

def test_similar_and_duplicate_articles_merge_into_one_event():
    docs = [doc(1, title="삼성전자 HBM4 공급 확대 기대", d=0), doc(2, title="[속보] 삼성전자 HBM4 공급 확대 기대", d=0, source="naver_blog"),
            doc(3, title="삼성전자 HBM4 공급 확대 기대감", d=1), doc(4, title="삼성전자 신공장 가동 시작", d=0)]
    ev = sn.n11(sn.clean_inputs(inputs(docs=docs), AS_OF), AS_OF).artifacts["events"]
    sizes = sorted(e["n_docs"] for e in ev)
    assert sizes == [1, 3]
    big = next(e for e in ev if e["n_docs"] == 3)
    assert big["sources"] == ["naver_blog", "naver_news"]


def test_far_apart_same_title_are_separate_events():
    docs = [doc(1, title="삼성전자 실적 발표", d=0), doc(2, title="삼성전자 실적 발표", d=10)]
    assert len(sn.cluster([dict(d, d=d["d"]) for d in docs])) == 2


def test_uncertainty_share_is_computed_from_expression_words():
    docs = [doc(1, title="삼성전자 파업 우려", summary="삼성전자 노조 파업 가능성에 우려가 커졌다.", score=-0.6, label="negative"),
            doc(2, title="삼성전자 파업 우려 확산", summary="삼성전자 노조 파업 가능성에 우려.", score=-0.5, label="negative"),
            doc(3, title="삼성전자 파업 우려 속 주가", summary="삼성전자 주가는 평온", score=-0.4, label="negative")]
    ev = sn.n11(sn.clean_inputs(inputs(docs=docs), AS_OF), AS_OF)
    e = ev.artifacts["events"][0]
    k = e["uncertainty_key"]
    assert ev.artifacts["ledger"][k]["unit"] == "%" and ev.artifacts["ledger"][k]["value"] == pytest.approx(100.0)   # 제목에 '우려' 포함
    assert e["tone"] == "우려"


def test_conflicting_labels_inside_one_event_go_to_ambiguity_and_conflict_zone():
    docs = [doc(1, title="삼성전자 실적 발표 기대", score=0.6, label="positive"),
            doc(2, title="삼성전자 실적 발표 우려", summary="삼성전자 실적 발표를 두고 우려가 나왔다.", score=-0.6, label="negative")]
    r = sn.n11(sn.clean_inputs(inputs(docs=docs), AS_OF), AS_OF)
    assert r.artifacts["events"] and len(r.artifacts["ambiguity"]) == 1
    a = r.artifacts["ambiguity"][0]
    assert a["labels"] == {"positive": 1, "negative": 1} and sorted(a["doc_ids"]) == [1, 2]
    assert len(r.conflicts) == 1 and len(r.conflicts[0].views) == 2 and all(v.evidence_links for v in r.conflicts[0].views)
    assert nodes.result_problems(r) == []                                         # 평균 내지 않고 나란히


# ---- N11: 에이전트 3 와 같은 값

def test_legacy_sentiment_indicators_equal_agent3_for_same_input():
    b = _sent_bundle()
    full = a3.compute(copy.deepcopy(b), CO, AS_OF)["facts"]
    inp = inputs(grouped=copy.deepcopy(b["docs"]), search=copy.deepcopy(b["search"]))
    led = sn.n11(sn.clean_inputs(inp, AS_OF), AS_OF).artifacts["agent3_sentiment_facts"]
    new = {v["label"]: v["value"] for v in led.values()}
    old = {v["label"]: v["value"] for v in full.items.values()}
    shared = [l for l in new if l in old]
    assert len(shared) >= 3 and {"뉴스 감성(최근 7일)", "검색 관심도 배율(최근 7일 ÷ 직전 90일)"} <= set(shared)
    assert all(new[l] == pytest.approx(old[l]) for l in shared)


# ---- 한계·기준일

def test_date_granularity_limit_is_stated_and_window_is_daily():
    res = run(ext=True)["results"]
    for nid in ("N11", "N12"):
        assert any("날짜 단위" in x and "장중·장후" in x for x in res[nid].artifacts["limits"])
    assert res["N12"].artifacts["definitions"]["CAR"].startswith("사건일 다음 거래일부터")


def test_future_rows_are_removed_by_tool_layer():
    d = inputs()
    d["docs"].append(doc(999, d=-3, title="삼성전자 미래 기사", score=0.9))
    d["daily"].append({"d": day(-3), "n": 5, "score": 0.99})
    d["price"].append({"d": day(-3), "v": 1.0})
    c = sn.clean_inputs(d, AS_OF)
    assert all(str(r["d"]) <= AS_OF for k in ("docs", "daily", "price") for r in c[k])
    with pytest.raises(ValueError):
        sn.run_sentiment_agent("005930", "", inputs=d)


# ---- 노드 틀 연결

def test_no_documents_is_data_insufficient_and_extension_skipped():
    r = run(ext=True, docs=[], grouped=[], docs_agg=None)
    assert r["results"]["N11"].status == "DATA_INSUFFICIENT" and r["status"] == "DATA_INSUFFICIENT"
    assert r["nodes"][1]["state"] == "skipped" and r["counts"]["executed"] == 1


def test_extension_skipped_without_price_history_with_reason():
    r = run(ext=True, price=[], kospi=[])
    ext = r["nodes"][1]
    assert ext["state"] == "skipped" and ext["missingInputs"] == ["price_after_event"] and r["counts"]["executed"] == 1


def test_base_only_and_both_counts():
    assert run(ext=False)["counts"] == {"base": 1, "extSelected": 0, "extExecuted": 0, "executed": 1}
    assert run(ext=True)["counts"] == {"base": 1, "extSelected": 1, "extExecuted": 1, "executed": 2}
    assert {"N11", "N12"} <= set(nodes.RUNNERS)


# ---- N12

def test_n12_car_table_has_three_windows_and_starts_after_event_day():
    res = run(ext=True)["results"]["N12"]
    rows = res.artifacts["car_table"]
    assert rows and all(len(r["keys"]) == 3 for r in rows)
    led = res.artifacts["ledger"]
    assert {led[k]["label"].rsplit(" ", 1)[1] for k in rows[0]["keys"]} == {"t+1", "t+3", "t+5"}
    daily, price, kospi = series()
    ar = sn.abnormal_returns(sn.series_points(price), sn.series_points(kospi))
    d = rows[0]["date"]
    first_after = next(i for i, (x, _) in enumerate(ar) if x > d)
    assert rows[0]["car_t+3"] == pytest.approx(sum(v for _, v in ar[first_after:first_after + 3]))      # 사건 당일 제외, 다음 거래일부터


def test_n12_skips_inference_when_model_unvalidated_but_keeps_tables():
    r = run(ext=True, effect=2.0, validated=False)
    res = r["results"]["N12"]
    assert res.artifacts["car_table"] and res.artifacts["incremental_power"]
    assert "SENT_MODEL_UNVALIDATED" in res.prediction_skipped_reason
    assert not any(f.tag == "Prediction" for f in res.findings)
    assert r["prediction_skipped_reason"] == res.prediction_skipped_reason and r["status"] == "PARTIAL_SUCCESS"


def test_n12_skips_for_small_sample_with_reason():
    assert run(ext=True, validated=True, n=40)["nodes"][1]["state"] == "skipped"        # 틀: 입력 요건 미충족
    res = sn.n12(sn.clean_inputs(inputs(n=40), AS_OF), AS_OF, validated=True)             # 직접 호출해도 추론 안 함
    assert "최소" in res.prediction_skipped_reason and not any(f.tag == "Prediction" for f in res.findings)


def test_n12_skips_when_sentiment_adds_no_predictive_power():
    res = run(ext=True, validated=True, effect=0.0)["results"]["N12"]                 # 수익률과 감성이 무관
    assert not any(f.tag == "Prediction" for f in res.findings)
    assert "추가 예측력이 유의하지 않음" in res.prediction_skipped_reason


def test_n12_emits_inference_only_when_validated_significant_and_enough_samples():
    res = run(ext=True, validated=True, effect=2.0)["results"]["N12"]                  # 다음 날 수익이 감성 변화에 비례
    pw = {p["h"]: p for p in res.artifacts["incremental_power"]}
    assert pw[1]["t_stat"] > 1.96 and pw[1]["mse_with_sentiment"] < pw[1]["mse_base"]
    assert res.prediction_skipped_reason is None and res.status == "SUCCESS"
    pred = [f for f in res.findings if f.tag == "Prediction"]
    assert len(pred) == 1 and pred[0].evidence_links and "인과가 아니며 투자 권유가 아님" in pred[0].text
    assert all(k in res.artifacts["ledger"] for f in res.findings for k in f.evidence_links)


def test_incremental_power_uses_only_past_data_for_each_prediction():
    daily, price, kospi = series(150, effect=2.0)
    ar = sn.abnormal_returns(sn.series_points(price), sn.series_points(kospi))
    days = sn._day_series(daily)
    p = sn.incremental_power(days, ar, 1)
    assert p["oos"] == p["n"] - int(p["n"] * 0.6) and p["mse_with_sentiment"] < p["mse_base"]
    assert sn.incremental_power(days[:40], ar, 1)["mse_base"] is None                    # 표본 부족이면 수치를 내지 않음


# ---- 공통 금지

def test_no_investment_advice_or_target_price_in_any_output():
    r = run(ext=True, validated=True, effect=2.0)
    blob = " ".join(f.text for res in r["results"].values() for f in res.findings)
    assert not re.search(r"매수\s*(추천|의견)|매도\s*(추천|의견)|목표\s*주가|사세요|파세요", blob)


def test_all_findings_pass_validation_and_tags():
    for nid, res in run(ext=True, validated=True, effect=2.0)["results"].items():
        assert nodes.result_problems(res) == [], nid
        assert all(f.tag in nodes.TAGS for f in res.findings)


# ---- PM 결정(11/2): 사건일 문서 3건 조건, 부수 언급 한계

def test_event_day_needs_three_documents_and_twenty_prior_observations():
    days = [(f"2026-01-{i + 1:02d}", 0.0 + (i % 2) * 0.01, 5) for i in range(25)]
    days[22] = ("2026-01-23", 0.9, 2)                                # 크게 벗어났지만 문서 2건
    assert sn.event_days(days) == [] or all(d != "2026-01-23" for d, _ in sn.event_days(days))
    days[22] = ("2026-01-23", 0.9, 3)
    assert "2026-01-23" in [d for d, _ in sn.event_days(days)]
    assert sn.event_days(days[:20]) == []                           # 직전 관측일 20개 미만이면 사건일 없음


def test_mention_limit_is_shown_in_n11_and_n12():
    res = run(ext=True)["results"]
    for nid in ("N11", "N12"):
        assert any("부수적으로 언급" in x and "종목 태그 매핑 미적용" in x for x in res[nid].artifacts["limits"])


def test_sentiment_limit_wording_uses_eval_result():
    from ch_agents.sentiment_limit import SENT_LIMIT_TEXT
    from ch_agents.p03 import STATUS_TEXT
    assert "56.6%" in SENT_LIMIT_TEXT and "600건" in SENT_LIMIT_TEXT and "440건" in SENT_LIMIT_TEXT and "개선 전" in SENT_LIMIT_TEXT
    assert STATUS_TEXT["SENT_MODEL_UNVALIDATED"] == SENT_LIMIT_TEXT
    assert "검증됨" not in SENT_LIMIT_TEXT and "평가 전" not in SENT_LIMIT_TEXT
    from ch_agents.llm import BANNED
    assert not any(w in SENT_LIMIT_TEXT for w in BANNED)


def test_sentiment_limit_survives_masking_and_sentence_check():
    from ch_agents.sentiment_limit import SENT_LIMIT_TEXT
    from ch_agents.node_agents import _mask_loose_numbers
    from ch_agents import llm
    masked = _mask_loose_numbers(f"{SENT_LIMIT_TEXT} (SENT_MODEL_UNVALIDATED)")
    assert "56.6%" in masked and "440건" in masked and "수치는 노드 산출물 참조" not in masked
    assert "(수치는 노드 산출물 참조)" in _mask_loose_numbers("Brier 0.265")   # 다른 수치는 계속 가림
    assert llm.sentence_problems("감성 점수는 " + SENT_LIMIT_TEXT + "입니다.", set(), llm.label_terms(None)) == []
