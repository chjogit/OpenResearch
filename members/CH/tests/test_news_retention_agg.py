"""#15 2주 보관: 메인 뉴스·유튜브 댓글을 지우기 전 일별 집계로 남기면 에이전트 3 지표가 삭제 전·후 같은지 (LLM 없이, 모의)."""
from collections import defaultdict
from datetime import date, timedelta

from ch_agents import agents, db, agent3_sentiment_flow as s3
from conftest import CO
from test_compute import _sent_bundle

AS_OF = "2026-10-25"
KEEP_DAYS = 11   # 실제 보관은 14일(kic-agent-data retention.DEFAULT_DAYS)이나, 비교 창(직전 7일=8~13일)이 14일 안이라 창 안쪽에서 잘라야 집계 합성 검증이 의미 있다(#76)


def _day(k):
    return (date.fromisoformat(AS_OF) - timedelta(days=k)).isoformat()


def _docs():
    """문서 단위 (일자, 소스, 점수|None). 최근 7일·직전 7일·그 이전 모두, 뉴스·댓글·블로그가 섞이고 점수 없는 문서 포함."""
    out = []
    for k in range(0, 30):
        for i in range(4 + k % 4):          # 직전 7일(8~14일) 창이 최소 20건을 넘게
            out.append((_day(k), "naver_news", round(0.4 - 0.03 * k + 0.05 * i, 4) if (k + i) % 5 else None))
        if k % 3 == 0:
            out.append((_day(k), "finnhub_news", 0.1 * (k % 4) - 0.15))
        if k % 2 == 0:
            out.append((_day(k), "youtube_comment", -0.2 + 0.01 * k))
        if k % 4 == 1:
            out.append((_day(k), "naver_blog", 0.05 * (k % 3)))
    return out


def _live_rows(docs):
    """에이전트 3 메인 SQL 'docs' 와 같은 계산: (일자, 소스)별 점수 붙은 문서 수와 평균."""
    acc = defaultdict(list)
    for d, src, score in docs:
        acc[(d, src)].append(score)
    rows = []
    for (d, src), scores in acc.items():
        sc = [x for x in scores if x is not None]
        rows.append({"d": d, "source": src, "n": len(sc), "score": sum(sc) / len(sc) if sc else None})
    return rows


def _agg_rows(docs):
    """kic-agent-data retention.aggregate → core.doc_daily_agg → DOC_AGG_SQL 과 같은 계산 (n_scored, score_sum/n_scored)."""
    acc = defaultdict(lambda: [0, 0, 0.0])
    for d, src, score in docs:
        a = acc[(d, src)]
        a[0] += 1
        if score is not None:
            a[1] += 1
            a[2] += score
    return [{"d": d, "source": src, "n": ns, "score": sm / ns if ns else None} for (d, src), (_, ns, sm) in acc.items()]


def _facts(b):
    f = s3.compute(b, CO, AS_OF)["facts"]
    return ({v["label"]: (round(v["value"], 9) if isinstance(v["value"], float) else v["value"], v.get("note"))
             for v in f.items.values()}, sorted(g["label"] for g in f.gaps), list(f.flags))


def test_news_and_comment_metrics_same_before_and_after_two_week_purge():
    docs = _docs()
    cutoff = _day(KEEP_DAYS)
    before = _facts(_sent_bundle(docs=_live_rows(docs)))
    gone = [x for x in docs if x[0] < cutoff and x[1] in ("naver_news", "finnhub_news", "youtube_comment")]
    live = [x for x in docs if x not in gone]
    assert gone and {x[1] for x in gone} == {"naver_news", "finnhub_news", "youtube_comment"}
    after = _facts(_sent_bundle(docs=_live_rows(live), docs_agg=_agg_rows(gone)))
    assert after == before
    assert _facts(_sent_bundle(docs=_live_rows(live), docs_agg=None)) != before   # 집계를 안 읽으면 기준선이 달라짐


def test_metrics_same_when_blog_and_news_both_purged():
    docs = _docs()
    cutoff = _day(KEEP_DAYS)
    before = _facts(_sent_bundle(docs=_live_rows(docs)))
    gone = [x for x in docs if x[0] < cutoff]
    live = [x for x in docs if x[0] >= cutoff]
    # 메인 집계(뉴스·댓글) + kic-opinion 집계(블로그) 를 fetch_bundle 처럼 이어 붙임
    main_agg = _agg_rows([x for x in gone if x[1] != "naver_blog"])
    op_agg = _agg_rows([x for x in gone if x[1] == "naver_blog"])
    assert _facts(_sent_bundle(docs=_live_rows(live), docs_agg=main_agg + op_agg)) == before


def _env(monkeypatch, split, main_agg, op_agg):
    if split:
        monkeypatch.setenv("OPINION_DATABASE_URL", "postgresql://x")
    else:
        monkeypatch.delenv("OPINION_DATABASE_URL", raising=False)
    log = {"q": [], "q_opinion": []}

    def q(sql, p=None, url=None):
        log["q"].append((sql, p))
        if isinstance(main_agg, Exception) and "doc_daily_agg" in sql:
            raise main_agg
        return list(main_agg) if "doc_daily_agg" in sql else []

    def q_opinion(sql, p=None):
        log["q_opinion"].append((sql, p))
        return list(op_agg) if "doc_daily_agg" in sql else []

    monkeypatch.setattr(db, "bundle", lambda sql, p: {"docs": []})
    monkeypatch.setattr(db, "q", q)
    monkeypatch.setattr(db, "q_opinion", q_opinion)
    monkeypatch.setattr(agents, "shared", lambda name, as_of, fn: None)
    return log


NEWS = {"d": "2026-10-05", "source": "naver_news", "n": 3, "score": 0.2}
BLOG = {"d": "2026-10-05", "source": "naver_blog", "n": 2, "score": -0.1}


def test_split_reads_main_news_agg_without_blog_and_opinion_agg(monkeypatch):
    log = _env(monkeypatch, True, [NEWS], [BLOG])
    out = agents.fetch_bundle(3, CO, AS_OF, use_rag=False)
    assert out["docs_agg"] == [NEWS, BLOG]
    main = [p for sql, p in log["q"] if "doc_daily_agg" in sql]
    assert main and main[0]["skip_src"] == list(db.OPINION_SOURCES)   # 메인 집계의 블로그·카페 행은 겹치므로 뺌
    assert [p["skip_src"] for sql, p in log["q_opinion"] if "doc_daily_agg" in sql] == [[]]


def test_without_split_reads_only_main_agg_unfiltered(monkeypatch):
    log = _env(monkeypatch, False, [NEWS, BLOG], [])
    out = agents.fetch_bundle(3, CO, AS_OF, use_rag=False)
    assert out["docs_agg"] == [NEWS, BLOG] and log["q_opinion"] == []
    assert [p["skip_src"] for sql, p in log["q"] if "doc_daily_agg" in sql] == [[]]


def test_missing_main_agg_table_keeps_opinion_agg(monkeypatch):
    _env(monkeypatch, True, RuntimeError('relation "core.doc_daily_agg" does not exist'), [BLOG])
    assert agents.fetch_bundle(3, CO, AS_OF, use_rag=False)["docs_agg"] == [BLOG]


def test_agg_sql_skips_sources_like_main_docs_query():
    assert "skip_src" in s3.DOC_AGG_SQL and "skip_src" in s3.SQL
