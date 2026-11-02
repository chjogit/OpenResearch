"""#21 E3: 조회 도구는 as_of_date 를 필수로 받고, 기준일 다음 날 이후 자료는 도구 계층에서 제거한다 (같은 날짜는 포함)."""
import pytest

from ch_agents import asof, db, rag, rag_hybrid
from conftest import AS_OF, CO   # AS_OF = 2026-10-26


def _news(day, doc_id):
    return {"doc_id": doc_id, "title": f"n{doc_id}", "published_at": f"{day}T00:00:00", "published": day}


def _disc(day, no):
    return {"rcept_no": no, "rcept_dt": day, "report_nm": "공시"}


def test_require_as_of_rejects_missing_and_invalid():
    for bad in (None, "", "내일", "2026-13-40"):
        with pytest.raises(ValueError):
            asof.require_as_of(bad)
    assert asof.require_as_of("2026-10-26") == "2026-10-26"
    assert asof.require_as_of("2026-10-26T09:00:00") == "2026-10-26"


def test_same_date_is_included_next_day_is_removed():
    rows = [_news("2026-10-25", 1), _news(AS_OF, 2), _news("2026-10-27", 3)]
    kept, n = asof.cut_future(rows, AS_OF)
    assert [r["doc_id"] for r in kept] == [1, 2] and n == 1               # 당일 포함, 다음 날부터 제거
    assert asof.cut_future(None, AS_OF) == ([], 0)
    with pytest.raises(ValueError):
        asof.cut_future(rows, None)


def test_rows_without_a_date_are_not_dropped_silently():
    kept, n = asof.cut_future([{"doc_id": 9}], AS_OF)
    assert kept == [{"doc_id": 9}] and n == 0


def test_rag_fetch_drops_future_rows_mixed_into_the_sql_bundle(monkeypatch):
    monkeypatch.setattr(db, "opinion_enabled", lambda: False)
    mixed = {"news": [_news("2026-10-24", 1), _news("2026-10-27", 2), _news("2026-11-02", 3)],
             "disclosures": [_disc("2026-10-26", "A1"), _disc("2026-10-28", "A2")]}
    monkeypatch.setattr(db, "bundle", lambda sql, p: mixed)
    out = rag.fetch(3, CO, AS_OF)
    assert [r["doc_id"] for r in out["news"]] == [1]
    assert [r["rcept_no"] for r in out["disclosures"]] == ["A1"]            # 공시일 당일은 포함
    assert out["asof_removed"] == {"news": 2, "disclosures": 1}


def test_rag_fetch_result_is_unchanged_when_no_future_rows(monkeypatch):
    monkeypatch.setattr(db, "opinion_enabled", lambda: False)
    clean = {"news": [_news("2026-10-24", 1)], "disclosures": []}
    monkeypatch.setattr(db, "bundle", lambda sql, p: dict(clean))
    assert rag.fetch(3, CO, AS_OF) == clean                                  # 표식도 안 붙음 (기존 결과와 같음)


def test_rag_fetch_requires_as_of(monkeypatch):
    monkeypatch.setattr(db, "opinion_enabled", lambda: False)
    monkeypatch.setattr(db, "bundle", lambda sql, p: {})
    with pytest.raises(ValueError):
        rag.fetch(3, CO, None)


def test_chunk_and_vector_tools_drop_future_chunks(monkeypatch):
    def hit(cid, day):
        return {"chunk_id": cid, "doc_id": cid, "content": "x", "published_at": f"{day}T00:00:00", "published": day,
                "source": "naver_news", "title": "t", "summary": "", "url": "u", "sim": 0.5}

    rows = [hit(1, "2026-10-20"), hit(2, AS_OF), hit(3, "2026-10-27"), hit(4, "2026-11-01")]
    run_sql = lambda sql, p: list(rows)                                      # noqa: E731  모의 SQL: 미래 행이 섞여 돌아옴
    chunks = rag_hybrid.fetch_chunks(3, CO, AS_OF, {}, embed=lambda q: [0.1, 0.2], run_sql=run_sql)
    assert [h["chunk_id"] for h in chunks["hits"]] == [1, 2]
    hyb = rag_hybrid.fetch_hybrid(3, CO, AS_OF, {}, embed=lambda q: [0.1, 0.2], run_sql=run_sql)
    assert [h["chunk_id"] for h in hyb["hits"]] == [1, 2]
    for fn in (rag_hybrid.fetch_chunks, rag_hybrid.fetch_hybrid):
        with pytest.raises(ValueError):
            fn(3, CO, "", {}, embed=lambda q: [0.1], run_sql=run_sql)


def test_all_future_chunks_removed_reports_no_chunks(monkeypatch):
    rows = [{"chunk_id": 1, "doc_id": 1, "published_at": "2026-11-01T00:00:00", "published": "2026-11-01"}]
    out = rag_hybrid.fetch_chunks(3, CO, AS_OF, {}, embed=lambda q: [0.1], run_sql=lambda s, p: list(rows))
    assert out == {"error": "청크 없음"}


def test_sql_tool_refuses_as_of_queries_without_as_of():
    with pytest.raises(ValueError):
        db.q("SELECT 1 WHERE d <= %(as_of)s::date", {})                      # 접속 전에 거절
    with pytest.raises(ValueError):
        db.q("SELECT 1 WHERE d <= %(as_of)s::date", {"as_of": ""})
