"""P03-F08 감성 평가셋 도구 시험 (DB 없이)."""
from ch_agents import sentiment_eval as se


def test_kappa_and_macro_f1_basic():
    a = ["positive", "negative", "neutral", "positive"]
    assert se.cohen_kappa(a, a) == 1.0
    assert se.macro_f1(["positive", "negative"], ["positive", "negative"]) == 1.0
    assert se.macro_f1(["positive", "negative"], ["negative", "positive"]) == 0.0


def test_score_uses_agreement_or_final_and_counts_none(tmp_path):
    rows = [
        {"doc_id": 1, "source": "naver_news", "label_a": "긍정", "label_b": "positive", "dict_label": "positive"},
        {"doc_id": 2, "source": "naver_news", "label_a": "negative", "label_b": "neutral", "dict_label": "negative"},
        {"doc_id": 3, "source": "naver_blog", "label_a": "negative", "label_b": "neutral", "label_final": "negative",
         "dict_label": "none"},
        {"doc_id": 4, "source": "naver_blog", "label_a": "무관", "label_b": "irrelevant", "dict_label": "positive"},
    ]
    out = se.score(rows)
    assert out["n_gold"] == 3                      # 2번은 불일치·조정 없음 → 제외
    assert round(out["irrelevant_share"], 2) == 33.33
    assert round(out["dict_none_share"], 2) == 33.33
    assert out["accuracy"] == 50.0                 # 1번 맞음, 3번 none→neutral 로 틀림 (무관 제외)
    assert out["confusion"]["negative"] == {"neutral": 1}


def test_sample_writes_blind_csv_and_merge(tmp_path):
    rows = [{"doc_id": 7, "source": "naver_news", "ticker": "005930", "name": "삼성전자", "published_at": "2026-10-27",
             "title": "t", "summary": "s", "dict_label": "positive", "dict_score": 0.8, "dict_method": "lexicon"}]
    p = se.sample(tmp_path / "blind.csv", "2026-10-28", rows=rows, blind=True)
    got = se.load(p)
    assert "dict_label" not in got[0] and got[0]["title"] == "t"
    got[0]["label_a"] = got[0]["label_b"] = "positive"
    merged = se.merge_dict_labels(got, rows)
    assert se.score(merged)["accuracy"] == 100.0
