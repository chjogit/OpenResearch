"""QA(#10): kic-opinion 분리 전후 동일성·대체 동작 검증 (DB 없이 모의 질의)."""
import random

import pytest

from ch_agents import agents, db, rag

CO = {"company_id": 1, "market": "KR", "ticker": "005930", "name": "삼성전자"}
AS_OF = "2026-10-29"


def _sql_order(rows):
    """rag.SQL 의 ORDER BY 와 같은 기준: 일치 수 ↓, 발행 시각 ↓, doc_id ↓."""
    return sorted(rows, key=lambda r: (-(len(r["tt"]) * 2 + len(r["st"])), _neg(r["published_at"]), -r["doc_id"]))


def _neg(ts):
    return tuple(-ord(ch) for ch in ts)


def _rows(n, seed):
    rnd = random.Random(seed)
    src = ["naver_news", "naver_blog", "naver_cafe", "youtube_comment"]
    return [{"doc_id": i, "source": rnd.choice(src), "tt": ["a"] * rnd.randint(0, 2), "st": ["s"] * rnd.randint(0, 2),
             "published_at": f"2026-10-{rnd.randint(1, 29):02d}T{rnd.randint(0, 23):02d}:00:00+00:00"}
            for i in range(1, n + 1)]


@pytest.mark.parametrize("seed", range(20))
def test_merge_of_split_candidates_equals_single_db_order(seed):
    """메인(뉴스 등) + kic-opinion(블로그·카페) 후보를 합친 결과가 한 DB 에서 정렬·LIMIT 한 결과와 같다."""
    rows = _rows(500, seed)
    whole = _sql_order(rows)[:300]
    main = _sql_order([r for r in rows if r["source"] not in db.OPINION_SOURCES])[:300]
    op = _sql_order([r for r in rows if r["source"] in db.OPINION_SOURCES])[:300]
    assert [r["doc_id"] for r in rag.merge_news(main, op)] == [r["doc_id"] for r in whole]


def test_rag_fetch_without_opinion_uses_single_main_query(monkeypatch):
    monkeypatch.delenv("OPINION_DATABASE_URL", raising=False)
    calls = []
    monkeypatch.setattr(db, "bundle", lambda sql, p: calls.append((sql, p)) or {"news": []})
    monkeypatch.setattr(db, "q_opinion", lambda *a, **k: pytest.fail("kic-opinion 을 읽으면 안 됨"))
    for aid in rag.PRESETS:
        calls.clear()
        rag.fetch(aid, CO, AS_OF)
        assert len(calls) == 1 and calls[0][0] == rag.SQL
        assert calls[0][1] == rag.params(aid, CO, AS_OF)   # 분리 전과 같은 질의·같은 출처


def test_rag_fetch_with_opinion_routes_blog_cafe(monkeypatch):
    monkeypatch.setenv("OPINION_DATABASE_URL", "postgresql://x")
    seen = {}
    monkeypatch.setattr(db, "bundle", lambda sql, p: seen.setdefault("main", p["sources"]) and {"news": [
        {"doc_id": 1, "tt": [], "st": [], "published_at": "2026-10-01"}]})
    monkeypatch.setattr(db, "q_opinion", lambda sql, p: seen.setdefault("op", p["sources"]) and [{"bundle": {"news": [
        {"doc_id": 2, "tt": ["a"], "st": [], "published_at": "2026-10-01"}]}}])
    aid = next(a for a, p in rag.PRESETS.items() if set(p.sources) & set(db.OPINION_SOURCES))
    out = rag.fetch(aid, CO, AS_OF)
    assert not set(seen["main"]) & set(db.OPINION_SOURCES)
    assert set(seen["op"]) <= set(db.OPINION_SOURCES)
    assert [r["doc_id"] for r in out["news"]] == [2, 1]


def _fake_bundle_env(monkeypatch, split):
    if split:
        monkeypatch.setenv("OPINION_DATABASE_URL", "postgresql://x")
    else:
        monkeypatch.delenv("OPINION_DATABASE_URL", raising=False)
    log = {"bundle": [], "q": [], "q_opinion": []}
    monkeypatch.setattr(db, "bundle", lambda sql, p: log["bundle"].append(p) or {"docs": [{"src": "news"}]})
    monkeypatch.setattr(db, "q", lambda sql, p=None, url=None: log["q"].append(sql) or [])
    monkeypatch.setattr(db, "q_opinion", lambda sql, p=None: log["q_opinion"].append(sql) or [{"src": "blog"}])
    monkeypatch.setattr(agents, "shared", lambda name, as_of, fn: None)
    return log


def test_agent3_bundle_without_opinion_is_unchanged(monkeypatch):
    log = _fake_bundle_env(monkeypatch, split=False)
    out = agents.fetch_bundle(3, CO, AS_OF, use_rag=False)
    assert log["bundle"][0]["skip_src"] == []          # 메인 SQL 이 블로그·카페를 빼지 않음 (분리 전과 같음)
    assert log["q_opinion"] == [] and out["docs"] == [{"src": "news"}]


def test_agent3_bundle_with_opinion_merges_blog_cafe(monkeypatch):
    log = _fake_bundle_env(monkeypatch, split=True)
    out = agents.fetch_bundle(3, CO, AS_OF, use_rag=False)
    assert log["bundle"][0]["skip_src"] == list(db.OPINION_SOURCES)
    assert out["docs"] == [{"src": "news"}, {"src": "blog"}]   # 메인 뉴스 + kic-opinion 블로그·카페
    assert len(log["q_opinion"]) == 2                    # docs_agg·docs 둘 다 kic-opinion 에서


def test_other_agents_never_skip_sources(monkeypatch):
    log = _fake_bundle_env(monkeypatch, split=True)
    for aid in agents.AGENTS:
        if aid == 3:
            continue
        log["bundle"].clear()
        try:
            agents.fetch_bundle(aid, CO, AS_OF, use_rag=False)
        except Exception:  # noqa: BLE001  다른 관점의 후처리는 모의 값과 안 맞을 수 있음 — 첫 질의 인자만 본다
            pass
        assert log["bundle"] and "skip_src" not in log["bundle"][0] or log["bundle"][0]["skip_src"] == []
