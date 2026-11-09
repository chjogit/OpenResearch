"""보관 기한으로 지운 블로그·카페 문서의 일별 집계를 에이전트 3 이 합쳐 읽는지: 삭제 전·후 지표 동일."""
from datetime import date, timedelta

from ch_agents import agents, agent3_sentiment_flow as s3
from conftest import CO
from test_compute import _sent_bundle

AS_OF_OLD = "2026-10-25"


def _day(k):
    return (date.fromisoformat(AS_OF_OLD) - timedelta(days=k)).isoformat()


def _blog_rows():
    """최근 7일 5일치(문서 많음) + 직전 7일(8~14일) 6일치 + 비교 창 밖(15~20일) 6일치. 일자별 (건수, 평균 점수)."""
    rows = [{"d": _day(k), "source": "naver_blog", "n": 6 + k, "score": 0.3 - 0.01 * k} for k in range(0, 5)]
    rows += [{"d": _day(k), "source": "naver_blog", "n": 4 + k % 3, "score": -0.1 + 0.02 * (k % 5)} for k in range(8, 21)]
    return rows


def _facts(b):
    f = s3.compute(b, CO, AS_OF_OLD)["facts"]
    return {v["label"]: (v["value"], v.get("note")) for v in f.items.values()}, sorted(g["label"] for g in f.gaps), list(f.flags)


def _split(rows, cutoff_k):
    """cutoff_k 일보다 오래된 일자는 '삭제'되어 집계 표로 옮겨졌다고 가정 (일자별 1행이라 평균 = 합/건수)."""
    live = [r for r in rows if r["d"] >= _day(cutoff_k)]
    gone = [r for r in rows if r["d"] < _day(cutoff_k)]
    return live, [dict(r) for r in gone]


def test_values_same_before_and_after_deletion():
    rows = _blog_rows()
    base = _sent_bundle()
    base["docs"] = [r for r in base["docs"] if r["source"] != "naver_blog"] + rows
    before = _facts(base)
    live, gone = _split(rows, 11)                           # 비교 창(직전 7일: 8~13일) 안쪽에서 잘라 집계가 값에 영향을 주게 함
    assert gone and live                                     # 일부만 지워진 상황
    after_b = {**base, "docs": [r for r in base["docs"] if r["source"] != "naver_blog"] + live, "docs_agg": gone}
    assert _facts(after_b) == before
    without_agg = {**after_b, "docs_agg": None}
    assert _facts(without_agg) != before                    # 집계를 안 읽으면 값이 달라짐 (이 테스트가 의미 있음을 확인)


def test_merge_docs_weights_by_count_and_is_identity_without_agg():
    docs = [{"d": "2026-10-20", "source": "naver_blog", "n": 3, "score": 0.5}]
    assert s3.merge_docs(docs, None) is docs and s3.merge_docs(docs, []) is docs
    out = s3.merge_docs(docs, [{"d": "2026-10-20", "source": "naver_blog", "n": 1, "score": -0.5},
                              {"d": "2026-10-19", "source": "naver_cafe", "n": 2, "score": 0.1}])
    by = {(r["d"], r["source"]): r for r in out}
    assert by[("2026-10-20", "naver_blog")]["n"] == 4 and abs(by[("2026-10-20", "naver_blog")]["score"] - 0.25) < 1e-12
    assert by[("2026-10-19", "naver_cafe")]["n"] == 2


def test_fetch_bundle_reads_agg_and_tolerates_missing_table(monkeypatch):
    monkeypatch.delenv("OPINION_DATABASE_URL", raising=False)   # .env 의 kic-opinion 접속 정보와 무관하게 분리 전 동작을 봄
    calls = []
    monkeypatch.setattr(agents.db, "bundle", lambda sql, p: {"x": 1})
    monkeypatch.setattr(agents.rag, "fetch", lambda a, co, as_of: {})
    monkeypatch.setattr(agents.db, "q", lambda sql, p=None: calls.append(sql) or [{"d": "2026-10-01", "source": "naver_blog", "n": 2, "score": 0.1}])
    out = agents.fetch_bundle(3, CO, AS_OF_OLD)
    assert out["docs_agg"][0]["n"] == 2 and any("doc_daily_agg" in c for c in calls)

    def boom(sql, p=None):
        raise RuntimeError('relation "core.doc_daily_agg" does not exist')
    monkeypatch.setattr(agents.db, "q", boom)
    assert agents.fetch_bundle(3, CO, AS_OF_OLD)["docs_agg"] is None


def test_other_agents_do_not_query_agg(monkeypatch):
    seen = []
    monkeypatch.setattr(agents.db, "bundle", lambda sql, p: {})
    monkeypatch.setattr(agents.rag, "fetch", lambda a, co, as_of: {})
    monkeypatch.setattr(agents.db, "q", lambda sql, p=None: seen.append(sql) or [])
    agents.fetch_bundle(7, CO, AS_OF_OLD)
    assert not any("doc_daily_agg" in s for s in seen)
