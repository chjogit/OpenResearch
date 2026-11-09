"""에이전트 6 투자심리·뉴스: N11 감성·불확실성(기본) · N12 후속 시장 반응 검증(확장) (티켓 #23, specs/agent-split.md '노드 상세').

- N11: 문서 단위 감성 점수를 사건(유사·중복 기사 묶음)으로 합치고, **모든 점수에 근거 원문 문장(문서 ID·가능하면 청크 ID)을 붙입니다.**
  근거 문장을 못 붙이는 점수는 내지 않습니다. 대상 기업을 언급하지 않는 문서는 분리하고, 분류가 엇갈리는 사건은 ambiguity 로 따로 둡니다.
  기존 에이전트 3 의 심리 지표(뉴스·블로그·카페 감성, 변화, 검색 관심)는 `agent3_sentiment_flow.compute` 를 그대로 써서 같은 입력이면 같은 값입니다.
- N12: 사건일 뒤 t+1·t+3·t+5 거래일 누적 초과수익(CAR, 코스피 대비)과 '감성 없는 순수 시계열 대비 추가 예측력'을 계산합니다.
  표본·기간이 모자라거나, 추가 설명력이 유의하지 않거나, 감성 모델이 검증 전(`SENT_MODEL_UNVALIDATED`)이면 **감성 기반 추론은 만들지 않고** 이유를 남깁니다.
- 한계: 게시 시각이 날짜 단위라 장중·장후를 구분하지 못하므로 사건 창은 일 단위(사건 당일은 제외, 다음 거래일부터)입니다.
- 숫자는 DB 값을 코드가 계산한 것(장부 키)이며 LLM 이 만들지 않습니다. 감성은 키워드 사전 기준선이고 투자 권유·목표주가는 없습니다.
"""
from __future__ import annotations

import re
from collections import Counter
from statistics import mean

from . import agent3_sentiment_flow as a3
from .asof import cut_future, require_as_of
from .facts import Facts, series_points
from .sentiment_limit import SENT_LIMIT_TEXT
from .nodes import Conflict, ConflictView, Finding, NodeResult, NodeTask, register

SRC_DOC = a3.SRC_DOC
NAMES = {"naver_news": "뉴스", "naver_blog": "블로그", "naver_cafe": "카페", "finnhub_news": "영문 뉴스", "youtube_comment": "유튜브 댓글"}
DATE_LIMIT = ("게시 시각이 날짜 단위(published_at)라 장중·장후를 구분할 수 없음: 사건 창은 일 단위이며 사건 당일은 포함, "
              "후속 반응은 다음 거래일(t+1)부터 셈")
SIM = 0.6               # 제목 글자 2-gram 유사도가 이 이상이면 같은 사건(유사·중복 기사)
TOP_EVENTS = 10         # N11 진술문으로 풀어 쓰는 사건 수(큰 사건 순)
LOOKBACK = 14           # 사건 표에 쓰는 최근 일수(원문이 남아 있는 보관 기한과 같음)
HORIZONS = (1, 3, 5)    # 사건 이후 거래일 (t+1·t+3·t+5)
MIN_DAYS = 60           # N12: 일별 감성이 있는 날 최소 수
MIN_EVENTS = 20         # N12: 사건일 최소 수
MIN_EVENT_DOCS = 3      # N12: 사건일은 그날 문서 3건 이상(소수 문서 잡음 제외, PM 결정 11/2)
MENTION_LIMIT = "블로그·카페 문서 기반 결과에는 기업명을 부수적으로 언급한 글이 섞일 수 있음(종목 태그 매핑 미적용)"
SENT_EVENT_Z = 1.0      # 사건일: 그날 평균 감성이 직전 평균에서 이 표준편차 이상 벗어난 날
UNCERTAIN = ("불확실", "우려", "가능성", "전망", "변동성", "관망", "예상", "논란", "리스크", "위험", "불안", "지연", "차질")

DOC_SQL = """
SELECT d.doc_id, d.source, d.title, left(coalesce(d.summary, ''), 400) AS summary, d.url, d.published_at::date AS d,
       s.score, s.label, s.method,
       (SELECT min(c.chunk_id) FROM rag.chunk c WHERE c.doc_id = d.doc_id) AS chunk_id
FROM rag.document d JOIN core.doc_sentiment s USING (doc_id)
WHERE d.company_id = %(cid)s AND d.published_at::date <= %(as_of)s::date
  AND d.published_at::date > %(as_of)s::date - %(days)s::int
  AND d.source = ANY(%(sources)s::text[])
ORDER BY d.published_at DESC, d.doc_id DESC
LIMIT 600
"""
DOC_SQL_OPINION = DOC_SQL.replace("       (SELECT min(c.chunk_id) FROM rag.chunk c WHERE c.doc_id = d.doc_id) AS chunk_id\n",
                                  "       NULL::bigint AS chunk_id\n")
DAILY_SQL = """
SELECT d.published_at::date AS d, count(s.score) AS n, avg(s.score) AS score
FROM rag.document d JOIN core.doc_sentiment s USING (doc_id)
WHERE d.company_id = %(cid)s AND d.published_at::date <= %(as_of)s::date
  AND d.published_at::date > %(as_of)s::date - 400 AND d.source = ANY(%(sources)s::text[])
GROUP BY 1
"""
DAILY_AGG_SQL = """
SELECT d, sum(n_scored) AS n, sum(score_sum) / NULLIF(sum(n_scored), 0) AS score
FROM core.doc_daily_agg
WHERE company_id = %(cid)s AND d <= %(as_of)s::date AND d > %(as_of)s::date - 400 AND source = ANY(%(sources)s::text[])
GROUP BY d
"""
GROUPED_SQL = """
SELECT d.published_at::date AS d, d.source, count(s.score) AS n, avg(s.score) AS score
FROM rag.document d JOIN core.doc_sentiment s USING (doc_id)
WHERE d.company_id = %(cid)s AND d.published_at::date <= %(as_of)s::date AND d.published_at::date > %(as_of)s::date - 30
  AND d.source = ANY(%(sources)s::text[])
GROUP BY 1, 2
"""
SERIES_SQL = """
SELECT json_build_object(
    'price', (SELECT json_agg(json_build_object('d', trade_date, 'v', close) ORDER BY trade_date)
              FROM core.price_daily WHERE company_id = %(cid)s AND trade_date <= %(as_of)s::date
                AND trade_date > %(as_of)s::date - INTERVAL '420 days'),
    'kospi', (SELECT json_agg(json_build_object('d', trade_date, 'v', close) ORDER BY trade_date)
              FROM core.market_index_daily WHERE symbol = '^KS11' AND trade_date <= %(as_of)s::date
                AND trade_date > %(as_of)s::date - INTERVAL '420 days'),
    'search', (SELECT json_agg(json_build_object('d', trade_date, 'v', ratio) ORDER BY trade_date)
               FROM core.search_trend WHERE subject = 'KR:' || %(ticker)s AND trade_date <= %(as_of)s::date
                 AND trade_date > %(as_of)s::date - INTERVAL '400 days')
) AS bundle
"""


# ---------------------------------------------------------------- 입력

def fetch_inputs(co: dict, as_of: str) -> dict:
    """DB 에서 문서 단위 감성·일별 감성·시세를 읽습니다(읽기 전용). 블로그·카페는 kic-opinion, 나머지는 메인."""
    from . import db

    as_of = require_as_of(as_of)
    main_src = [s for s in NAMES if s not in db.OPINION_SOURCES]
    op_src = [s for s in NAMES if s in db.OPINION_SOURCES]
    split = db.opinion_enabled()
    p = {"cid": co["company_id"], "ticker": co["ticker"], "as_of": as_of, "days": 30}
    msrc = main_src if split else list(NAMES)
    docs = db.q(DOC_SQL, {**p, "sources": msrc})
    grouped = db.q(GROUPED_SQL, {**p, "sources": msrc})
    daily = db.q(DAILY_SQL, {**p, "sources": msrc})
    reads = [(db.q, {**p, "sources": main_src if split else list(NAMES)})] + ([(db.q_opinion, {**p, "sources": op_src})] if split else [])
    for read, prm in reads:           # 보관 기한으로 지운 문서의 일별 집계(표가 없으면 건너뜀)
        try:
            daily += read(DAILY_AGG_SQL, prm) or []
        except Exception:  # noqa: BLE001
            pass
    if split:
        docs += db.q_opinion(DOC_SQL_OPINION, {**p, "sources": op_src})
        grouped += db.q_opinion(GROUPED_SQL, {**p, "sources": op_src})
        daily += db.q_opinion(DAILY_SQL, {**p, "sources": op_src})
    series = db.bundle(SERIES_SQL, p)
    docs_agg = []
    for read, prm in [(db.q, a3.params(co, as_of, db.OPINION_SOURCES if split else ()))] + ([(db.q_opinion, a3.params(co, as_of))] if split else []):
        try:
            docs_agg += read(a3.DOC_AGG_SQL, prm) or []
        except Exception:  # noqa: BLE001  보관 집계 표가 없으면 살아 있는 문서만
            pass
    return {"docs": docs, "grouped": grouped, "daily": daily, "docs_agg": docs_agg or None, "company": co, **series}


def clean_inputs(b: dict, as_of: str) -> dict:
    """E3: 기준일 다음 날 이후 문서·일별 감성·시세 행은 도구 계층에서 제거."""
    as_of = require_as_of(as_of)
    out = dict(b)
    for k in ("docs", "grouped", "daily", "docs_agg", "price", "kospi", "search"):
        if b.get(k) is not None:
            out[k] = cut_future(b[k], as_of, ("d",))[0]
    return out


def _day_series(daily: list[dict]) -> list[tuple[str, float, int]]:
    """일별 (날짜, 건수 가중 평균 감성, 건수), 오래된 순. 같은 날의 여러 행(문서 집계·보관 집계)은 건수 가중으로 합침."""
    acc: dict[str, list[float]] = {}
    for r in daily or []:
        n = int(r.get("n") or 0)
        if n and r.get("score") is not None:
            a = acc.setdefault(str(r["d"])[:10], [0.0, 0])
            a[0] += float(r["score"]) * n
            a[1] += n
    return [(d, s / n, n) for d, (s, n) in sorted(acc.items())]


def available_inputs(b: dict) -> set[str]:
    have = set()
    if any(r.get("score") is not None for r in b.get("docs") or []) or any(r.get("n") for r in b.get("docs_agg") or []):
        have.add("documents")
    days = _day_series(b.get("daily"))
    px = series_points(b.get("price"))
    if len(days) >= MIN_DAYS and len(px) > max(HORIZONS) + 1 and series_points(b.get("kospi")):
        have.add("price_after_event")
    return have


# ---------------------------------------------------------------- 공통

def _ledger(f: Facts) -> dict:
    return {k: {x: v[x] for x in ("label", "value", "unit", "text", "as_of", "source", "kind", "note")} for k, v in f.items.items()}


def _find(kind: str, text: str, tag: str, keys) -> Finding:
    return Finding(kind=kind, text=text, tag=tag, evidence_links=[k for k in keys if k])


def _bigrams(t: str) -> set[str]:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|<[^>]*>|&\w+;", " ", t or "")
    t = re.sub(r"[^0-9a-zA-Z가-힣]", "", t).lower()
    return {t[i:i + 2] for i in range(len(t) - 1)} or ({t} if t else set())


def _sim(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def cluster(docs: list[dict]) -> list[list[dict]]:
    """제목 유사도(2-gram Jaccard ≥ SIM)가 높고 게시일이 3일 안인 문서를 같은 사건으로 묶음(단일 연결)."""
    parent = list(range(len(docs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    grams = [_bigrams(d.get("title")) for d in docs]
    for i in range(len(docs)):
        for j in range(i):
            if abs((_date(docs[i]["d"]) - _date(docs[j]["d"])).days) <= 3 and _sim(grams[i], grams[j]) >= SIM:
                parent[find(i)] = find(j)
    groups: dict[int, list[dict]] = {}
    for i, d in enumerate(docs):
        groups.setdefault(find(i), []).append(d)
    return sorted(groups.values(), key=lambda g: (-len(g), -max(x["doc_id"] for x in g)))


def _date(x):
    from datetime import date

    return date.fromisoformat(str(x)[:10])


def mentions(doc: dict, names: list[str]) -> bool:
    text = f"{doc.get('title') or ''} {doc.get('summary') or ''}"
    return any(n and n in text for n in names)


def evidence_sentence(doc: dict, names: list[str]) -> str | None:
    """점수의 근거 원문 문장: 요약에서 대상 기업을 언급한 문장, 없으면 제목(제목이 기업을 언급할 때). 못 찾으면 None."""
    for s in re.split(r"(?<=[.!?。])\s+|\n", re.sub(r"<[^>]+>|&\w+;", " ", doc.get("summary") or "")):
        if s.strip() and any(n and n in s for n in names):
            return re.sub(r"\s+", " ", s).strip()[:200]
    title = re.sub(r"<[^>]+>|&\w+;", " ", doc.get("title") or "")
    if title.strip() and any(n and n in title for n in names):
        return re.sub(r"\s+", " ", title).strip()[:200]
    return None


def uncertainty_hits(doc: dict) -> list[str]:
    text = f"{doc.get('title') or ''} {doc.get('summary') or ''}"
    return [w for w in UNCERTAIN if w in text]


# ---------------------------------------------------------------- N11 감성·불확실성

def n11(b: dict, as_of: str) -> NodeResult:
    as_of = require_as_of(as_of)
    co = b.get("company") or {}
    names = [x for x in (co.get("name"), co.get("ticker")) if x]
    f = Facts("T")
    # ① 기존 에이전트 3 와 같은 심리 지표(논조·검색 관심): 같은 코드, 같은 입력 → 같은 값
    legacy = a3.compute({"docs": [dict(r) for r in b.get("grouped") or []], "docs_agg": b.get("docs_agg"), "search": b.get("search"),
                         "flows": [], "price": b.get("price"), "kospi": b.get("kospi")}, co, as_of)["facts"]
    arts: dict = {"limits": [DATE_LIMIT, MENTION_LIMIT, f"{SENT_LIMIT_TEXT} (SENT_MODEL_UNVALIDATED)"]}
    finds: list[Finding] = []
    missing: list[str] = []
    # ② 문서 단위: 대상 기업 분리, 근거 문장 없는 점수 제외
    cutoff = None
    docs_all = [dict(r, d=str(r["d"])[:10]) for r in b.get("docs") or []]
    if docs_all:
        from datetime import timedelta
        cutoff = (_date(as_of) - timedelta(days=LOOKBACK)).isoformat()
    recent = [r for r in docs_all if cutoff is None or r["d"] > cutoff]
    unscored = [r for r in recent if r.get("score") is None]
    target, off_target, no_evidence = [], [], []
    for r in recent:
        if r.get("score") is None:
            continue
        if not mentions(r, names):
            off_target.append(r)
            continue
        sent = evidence_sentence(r, names)
        if not sent:
            no_evidence.append(r)
            continue
        target.append(dict(r, evidence=sent))
    arts.update(window_days=LOOKBACK, n_docs=len(recent), n_unscored=len(unscored),
                separated_off_target=[{"doc_id": r["doc_id"], "source": r["source"], "title": r["title"]} for r in off_target][:50],
                withheld_no_evidence=[{"doc_id": r["doc_id"], "source": r["source"]} for r in no_evidence][:50])
    events, ambiguity = [], []
    for i, grp in enumerate(cluster(target), 1):
        scores = [float(x["score"]) for x in grp]
        labels = Counter(x.get("label") for x in grp)
        first = max(grp, key=lambda x: (x["d"], x["doc_id"]))
        k = f.add(f"사건 E{i} 평균 감성({len(grp)}건)", mean(scores), "score", first["d"], SRC_DOC, kind="calc", group="사건",
                  note="-1 부정 ~ +1 긍정, 키워드 사전 기반. 근거 문장은 artifacts.events[].evidence")
        hits = Counter(w for x in grp for w in uncertainty_hits(x))
        share = sum(1 for x in grp if uncertainty_hits(x)) / len(grp)
        ku = f.add(f"사건 E{i} 불확실성 표현 비율", share * 100, "%", first["d"], "키워드 사전(불확실성 표현)", kind="calc", group="사건",
                   note=f"제목·요약에 불확실성 표현이 있는 기사 비율. 표현: {', '.join(w for w, _ in hits.most_common(4)) or '없음'}")
        ev = {"event": f"E{i}", "date": first["d"], "n_docs": len(grp), "sources": sorted({x["source"] for x in grp}),
              "score_key": k, "uncertainty_key": ku, "tone": "기대" if mean(scores) > 0.05 else "우려" if mean(scores) < -0.05 else "중립",
              "labels": dict(labels),
              "evidence": [{"doc_id": x["doc_id"], "chunk_id": x.get("chunk_id"), "source": x["source"], "date": x["d"],
                            "score": float(x["score"]), "sentence": x["evidence"], "url": x.get("url")} for x in grp[:5]]}
        events.append(ev)
        links = [k, ku] + [f"doc:{x['doc_id']}" for x in grp[:5]]
        if i <= TOP_EVENTS:     # 진술문은 큰 사건 순 상위만, 나머지는 artifacts.events 에 전부 남김
            finds.append(_find("number", f"사건 E{i}({first['d']}, {len(grp)}건) 평균 감성 {f.items[k]['text']} · 불확실성 표현 "
                                         f"{f.items[ku]['text']} → {ev['tone']}. 근거: {grp[0]['evidence']}", "Computation", links))
        if "positive" in labels and "negative" in labels:   # 분류가 엇갈림
            ambiguity.append({"event": f"E{i}", "labels": dict(labels), "doc_ids": [x["doc_id"] for x in grp], "score_key": k})
            finds.append(_find("note", f"분류 불일치: 사건 E{i} 안에 긍정 {labels['positive']}건·부정 {labels['negative']}건이 섞임", "Fact",
                               [k] + [f"doc:{x['doc_id']}" for x in grp[:5]]))
    arts.update(events=events, ambiguity=ambiguity)
    if ambiguity:   # 관점별 충돌: 한 사건 안의 상반 분류를 평균 내지 않고 나란히
        conflicts = []
        for a in ambiguity:
            grp = next(g for g in cluster(target) if sorted(x["doc_id"] for x in g) == sorted(a["doc_ids"]))
            pos = max((x for x in grp if x.get("label") == "positive"), key=lambda x: x["score"])
            neg = min((x for x in grp if x.get("label") == "negative"), key=lambda x: x["score"])
            conflicts.append(Conflict(topic=f"사건 {a['event']} 논조", views=[
                ConflictView(text=f"긍정 분류: {pos['evidence']}", tag="Interpretation", evidence_links=[f"doc:{pos['doc_id']}"]),
                ConflictView(text=f"부정 분류: {neg['evidence']}", tag="Interpretation", evidence_links=[f"doc:{neg['doc_id']}"])]))
    else:
        conflicts = []
    # ③ 지난 기간 집계 기준선(원문은 보관 기한으로 삭제)·기존 지표
    led = _ledger(legacy)
    keep = {k: v for k, v in led.items() if v["label"].endswith(("감성(최근 7일)", "감성 변화(최근 7일 − 직전 7일)", "감성(직전 7일, 기준선)"))
            or v["label"].startswith("검색 관심도")}
    arts["agent3_sentiment_facts"] = keep            # 에이전트 3 와 같은 라벨·같은 값(보관 집계 포함)
    for k, v in keep.items():
        nk = f"T{len(f.items) + 1}"          # 장부 키 규칙(대문자+숫자)에 맞는 새 키. 값·라벨은 에이전트 3 와 같음
        f.items[nk] = {**v, "group": "논조"}
        finds.append(_find("number", f"{v['label']} {v['text']}", "Computation", [nk]))
    f.gaps += [g for g in legacy.gaps if g["label"].endswith("감성(최근 7일)") or "감성 변화" in g["label"] or g["label"].startswith("검색") or g["label"] == "문서 감성"]
    if not events:
        missing.append("근거 문장이 있는 대상 기업 기사")
    if no_evidence or off_target:
        missing.append(f"근거 문장을 붙이지 못해 점수를 내지 않은 문서 {len(no_evidence)}건, 대상 기업 아님으로 분리한 문서 {len(off_target)}건")
    arts.update(ledger=_ledger(f), gaps=f.gaps)
    status = "SUCCESS" if events and not f.gaps else "PARTIAL_SUCCESS"
    return NodeResult(status=status, node_id="N11", findings=finds, conflicts=conflicts, artifacts=arts,
                      evidence_links=sorted(f.items) + [f"doc:{e['doc_id']}" for ev in events for e in ev["evidence"]],
                      missing_items=missing, reason=None if status == "SUCCESS" else "일부 지표 자료 부족 또는 근거 문장 있는 기사 없음")


# ---------------------------------------------------------------- N12 후속 시장 반응 검증

def event_days(days: list[tuple[str, float, int]]) -> list[tuple[str, float]]:
    """사건일: 그날 문서가 MIN_EVENT_DOCS건 이상이고 평균 감성이 직전 20개 관측일 평균에서 SENT_EVENT_Z 표준편차 넘게 벗어난 날(직전 관측일 20개 미만이면 없음) → (날짜, 부호 있는 표준점수)."""
    out = []
    for i in range(20, len(days)):
        prev = [s for _, s, _ in days[i - 20:i]]
        mu = mean(prev)
        sd = (sum((x - mu) ** 2 for x in prev) / (len(prev) - 1)) ** 0.5
        if sd and days[i][2] >= MIN_EVENT_DOCS and abs(days[i][1] - mu) / sd >= SENT_EVENT_Z:
            out.append((days[i][0], (days[i][1] - mu) / sd))
    return out


def abnormal_returns(price: list[tuple[str, float]], kospi: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """일별 초과수익(%) = 종목 일 수익률 − 코스피 일 수익률. 같은 날짜가 양쪽에 있는 날만."""
    kd = dict(kospi)
    out = []
    for (d0, p0), (d1, p1) in zip(price, price[1:]):
        k0, k1 = kd.get(d0), kd.get(d1)
        if p0 and k0 and k1:
            out.append((d1, ((p1 / p0 - 1) - (k1 / k0 - 1)) * 100))
    return out


def car_table(ev_days: list[tuple[str, float]], ar: list[tuple[str, float]]) -> list[dict]:
    """사건일 뒤 t+1·t+3·t+5 누적 초과수익(CAR). 사건 당일은 장중/장후를 몰라 제외하고 다음 거래일부터."""
    days = [d for d, _ in ar]
    rows = []
    for d, z in ev_days:
        j = next((i for i, x in enumerate(days) if x > d), None)   # 사건일 다음 거래일
        if j is None:
            continue
        row = {"date": d, "z": z, "direction": "긍정 급변" if z > 0 else "부정 급변"}
        for h in HORIZONS:
            row[f"car_t+{h}"] = sum(v for _, v in ar[j:j + h]) if j + h <= len(ar) else None
        rows.append(row)
    return rows


def incremental_power(days: list[tuple[str, float, int]], ar: list[tuple[str, float]], h: int = 1) -> dict:
    """감성 없는 순수 시계열(전일 초과수익) 대비 추가 예측력: 걷기 검증(앞 60% 학습, 이후 한 날씩 재학습)으로
    h 일 뒤 초과수익을 맞출 때 '전일 초과수익만' 쓴 모형과 '+ 전일 감성 변화'를 더한 모형의 평균제곱오차를 비교합니다."""
    import numpy as np

    sd = {d: s for d, s, _ in days}
    sdates = sorted(sd)
    sidx = {d: i for i, d in enumerate(sdates)}
    d_ar = dict(ar)
    dates = [d for d, _ in ar]
    pairs = []                                  # (전일 초과수익, 전일 감성 변화, h일 뒤 초과수익)
    for i, d in enumerate(dates[:-h]):
        if d not in sidx or sidx[d] == 0:
            continue
        pairs.append((d_ar[d], sd[d] - sd[sdates[sidx[d] - 1]], d_ar[dates[i + h]]))
    n = len(pairs)
    out = {"n": n, "h": h, "oos": 0, "mse_base": None, "mse_with_sentiment": None, "t_stat": None}
    if n < MIN_DAYS:
        return out
    x0 = np.array([[1.0, p[0]] for p in pairs])
    x1 = np.array([[1.0, p[0], p[1]] for p in pairs])
    y = np.array([p[2] for p in pairs])
    e0, e1 = [], []
    for t in range(int(n * 0.6), n):
        e0.append(y[t] - x0[t] @ np.linalg.lstsq(x0[:t], y[:t], rcond=None)[0])
        e1.append(y[t] - x1[t] @ np.linalg.lstsq(x1[:t], y[:t], rcond=None)[0])
    e0, e1 = np.array(e0), np.array(e1)
    out.update(oos=len(e0), mse_base=float((e0 ** 2).mean()), mse_with_sentiment=float((e1 ** 2).mean()))
    d = e0 ** 2 - e1 ** 2                       # 양수면 감성 모형이 더 정확
    if len(d) > 1 and d.std(ddof=1) > 0:
        out["t_stat"] = float(d.mean() / (d.std(ddof=1) / len(d) ** 0.5))
    return out


def n12(b: dict, as_of: str, validated: bool = False) -> NodeResult:
    """validated: 감성 모델이 사람 라벨 평가를 통과했는지(현재 False → 감성 기반 추론은 항상 건너뜀, 표는 그대로 냄)."""
    as_of = require_as_of(as_of)
    f = Facts("R")
    days = _day_series(b.get("daily"))
    ar = abnormal_returns(series_points(b.get("price")), series_points(b.get("kospi")))
    ev = event_days(days)
    finds: list[Finding] = []
    arts: dict = {"limits": [DATE_LIMIT, MENTION_LIMIT], "n_days": len(days), "n_events": len(ev),
                  "definitions": {"사건일": f"그날 평균 감성이 직전 20개 관측일 평균에서 {SENT_EVENT_Z:g} 표준편차 이상 벗어난 날이며 그날 문서가 {MIN_EVENT_DOCS}건 이상(직전 관측일이 20개 미만이면 사건일 없음)",
                                  "CAR": "사건일 다음 거래일부터 h 거래일 동안의 (종목 일 수익률 − 코스피 일 수익률) 합, %",
                                  "추가 예측력": "전일 초과수익만 쓴 모형 대비 전일 감성 변화를 더한 모형의 걷기 검증 평균제곱오차(MSE)"}}
    rows = []
    for r in car_table(ev, ar):
        if all(r[f"car_t+{h}"] is not None for h in HORIZONS):
            keys = [f.add(f"{r['date']} 사건 CAR t+{h}", r[f"car_t+{h}"], "%chg", r["date"], "core.price_daily × ^KS11",
                          kind="calc", group="사건 반응") for h in HORIZONS]
            rows.append({**r, "keys": keys})
    arts["car_table"] = rows
    for r in rows[-5:]:
        finds.append(_find("number", f"{r['date']} {r['direction']} 뒤 초과수익(코스피 대비) 누적: " +
                           ", ".join(f"t+{h} {f.items[k]['text']}" for h, k in zip(HORIZONS, r["keys"])), "Computation", r["keys"]))
    pw = [incremental_power(days, ar, h) for h in (1, 3, 5)] if len(days) >= MIN_DAYS else []
    arts["incremental_power"] = pw
    mse_keys = []
    for p in pw:
        if p.get("mse_base") is not None:
            kb = f.add(f"t+{p['h']} 초과수익 걷기 검증 MSE(감성 없는 기준 모형)", p["mse_base"], "coef", as_of,
                       "core.price_daily × ^KS11", kind="calc", group="추가 예측력")
            kw = f.add(f"t+{p['h']} 초과수익 걷기 검증 MSE(+ 감성 변화)", p["mse_with_sentiment"], "coef", as_of, SRC_DOC,
                       kind="calc", group="추가 예측력")
            mse_keys += [kb, kw]
            finds.append(_find("number", f"t+{p['h']}: 감성 없는 기준 모형 MSE {f.items[kb]['text']} vs 감성 변화 추가 모형 "
                                         f"{f.items[kw]['text']} (검증 {p['oos']}일)", "Computation", [kb, kw]))
    # 감성 기반 추론 게이트 (E2): 하나라도 미충족이면 추론을 만들지 않고 이유를 남김
    why = []
    if not validated:
        why.append(f"SENT_MODEL_UNVALIDATED: {SENT_LIMIT_TEXT}")
    if len(days) < MIN_DAYS:
        why.append(f"감성이 있는 날 {len(days)}일 (최소 {MIN_DAYS}일)")
    if len(ev) < MIN_EVENTS:
        why.append(f"사건일 {len(ev)}건 (최소 {MIN_EVENTS}건)")
    sig = [p for p in pw if p.get("t_stat") is not None]
    if sig and not any(p["t_stat"] > 1.96 and p["mse_with_sentiment"] < p["mse_base"] for p in sig):
        why.append("벤치마크 대비 추가 예측력이 유의하지 않음 (걷기 검증 오차가 개선되지 않음)")
    elif not sig and len(days) >= MIN_DAYS:
        why.append("추가 예측력 검증에 필요한 표본이 부족")
    reason = ("SENT_INFERENCE_SKIPPED: " + "; ".join(why)) if why else None
    if reason is None:
        finds.append(_find("conclusion", "감성 변화가 벤치마크 대비 추가 예측력을 보임(걷기 검증). 인과가 아니며 투자 권유가 아님",
                           "Prediction", mse_keys))
    arts.update(ledger=_ledger(f), gaps=f.gaps)
    return NodeResult(status="PARTIAL_SUCCESS" if reason or not rows else "SUCCESS", node_id="N12", findings=finds,
                      artifacts=arts, evidence_links=sorted(f.items), prediction_skipped_reason=reason, reason=reason,
                      missing_items=[] if rows else ["사건 이후 가격·거래량으로 반응을 잰 사건일"])


# ---------------------------------------------------------------- 노드 틀 연결

def make_runners(loader, validated: bool = False):
    cache: dict = {}

    def get(task: NodeTask) -> dict:
        key = (task.target_ticker, task.as_of_date)
        if key not in cache:
            cache[key] = clean_inputs(loader(task), task.as_of_date)
        return cache[key]

    return {"N11": lambda t: n11(get(t), t.as_of_date), "N12": lambda t: n12(get(t), t.as_of_date, validated)}


def _db_loader(task: NodeTask) -> dict:
    from . import db

    return fetch_inputs(db.company(task.target_ticker), task.as_of_date)


for _nid, _fn in make_runners(_db_loader).items():
    register(_nid)(_fn)


def run_sentiment_agent(ticker: str, as_of_date: str, extension: bool = False, inputs: dict | None = None,
                        validated: bool = False) -> dict:
    """에이전트 6 을 노드 단위로 실행. inputs 를 주면 DB 를 읽지 않습니다(재현·테스트)."""
    from .nodes import run_agent_nodes

    as_of = require_as_of(as_of_date)
    if inputs is None:
        from . import db

        inputs = fetch_inputs(db.company(ticker), as_of)
    inputs = clean_inputs(inputs, as_of)
    return run_agent_nodes(6, ticker, as_of, extension=extension, available=available_inputs(inputs),
                           runners=make_runners(lambda t: inputs, validated))
