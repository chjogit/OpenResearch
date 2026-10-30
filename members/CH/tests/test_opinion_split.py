"""블로그·카페 분리(kic-opinion) 오프라인 테스트: DB 없이 순수 부분만."""
from ch_agents import agent3_sentiment_flow as a3
from ch_agents import db, rag


def _n(i, tt, st, ts):
    return {"doc_id": i, "tt": tt, "st": st, "published_at": ts}


def test_merge_news_orders_by_match_then_recency_and_limits():
    a = [_n(1, ["a"], [], "2026-10-01"), _n(2, [], [], "2026-10-05")]
    b = [_n(3, ["a"], [], "2026-10-09"), _n(4, ["a", "b"], ["x"], "2026-09-01")]
    assert [r["doc_id"] for r in rag.merge_news(a, b)] == [4, 3, 1, 2]
    assert [r["doc_id"] for r in rag.merge_news(a, b, limit=2)] == [4, 3]


def test_merge_news_keeps_main_result_when_nothing_to_merge():
    a = [_n(1, [], [], "2026-10-01")]
    assert rag.merge_news(a, None) == a and rag.merge_news(None, None) is None


def test_opinion_enabled_follows_env(monkeypatch):
    monkeypatch.delenv("OPINION_DATABASE_URL", raising=False)
    assert db.opinion_enabled() is False
    monkeypatch.setenv("OPINION_DATABASE_URL", "postgresql://x")
    assert db.opinion_enabled() is True


def test_agent3_params_skip_src_default_empty_keeps_old_behavior():
    co = {"company_id": 1, "ticker": "005930"}
    assert a3.params(co, "2026-10-30")["skip_src"] == []
    assert a3.params(co, "2026-10-30", db.OPINION_SOURCES)["skip_src"] == ["naver_blog", "naver_cafe"]


def test_q_opinion_requires_setting(monkeypatch):
    monkeypatch.delenv("OPINION_DATABASE_URL", raising=False)
    import pytest

    with pytest.raises(RuntimeError):
        db.q_opinion("select 1")
