"""P03-F08 감성 평가셋: 사람 라벨 표본 만들기와 채점 (docs/P03_투자심리수급_상세개발기획서.md 14.1).

순서
1. sample(): 출처(뉴스·블로그·카페·유튜브 댓글)×사전 라벨(긍정·부정·중립·점수 없음)로 층화한 표본을 뽑아 CSV 로 저장.
   사전 점수는 CSV 에 넣되 라벨러용 열(label_a·label_b)과 분리합니다. 라벨러는 사전 점수를 보지 않고 라벨을 답니다
   (열을 숨기거나 `blind=True` 로 사전 열을 빼고 저장).
2. 라벨러 두 명이 label_a·label_b 에 negative / neutral / positive / irrelevant(종목 무관) 중 하나를 적음.
3. score(): 두 라벨러의 일치도(코헨 카파), 불일치 조정 뒤 정답과 사전 라벨의 정확도·매크로 F1·혼동표,
   출처별 결과, '점수 없음'(사전 키워드가 하나도 안 걸린 문서) 비율을 냅니다.

같은 LLM 의 출력을 정답으로 쓰지 않습니다(P01 24장). 이 모듈은 숫자를 만들지 않고 사람 라벨을 셉니다.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

LABELS = ("negative", "neutral", "positive")
GOLD = LABELS + ("irrelevant",)
SOURCES = ("naver_news", "naver_blog", "naver_cafe", "youtube_comment")
DICT_LABELS = ("negative", "neutral", "positive", "none")

SAMPLE_SQL = """
WITH d AS (
    SELECT d.doc_id, d.source, c.ticker, c.name, d.published_at, d.title, left(coalesce(d.summary, ''), 400) AS summary,
           s.label AS dict_label, s.score AS dict_score, s.method AS dict_method,
           row_number() OVER (PARTITION BY d.source, s.label ORDER BY md5(d.doc_id::text || %(seed)s)) AS rn
    FROM rag.document d
    JOIN core.doc_sentiment s USING (doc_id)
    LEFT JOIN core.company c ON c.company_id = d.company_id
    WHERE d.source = ANY(%(sources)s) AND d.published_at <= %(as_of)s::date
)
SELECT doc_id, source, ticker, name, published_at, title, summary, dict_label, dict_score, dict_method
FROM d WHERE rn <= %(per_cell)s
ORDER BY md5(doc_id::text || %(seed)s)
"""
FIELDS = ["doc_id", "source", "ticker", "name", "published_at", "title", "summary", "label_a", "label_b", "label_final",
          "note", "dict_label", "dict_score", "dict_method"]
BLIND_DROP = ("dict_label", "dict_score", "dict_method")


def sample(path: str | Path, as_of: str, per_cell: int = 38, seed: str = "p03-f08-v1", blind: bool = False,
           rows: list[dict] | None = None) -> Path:
    """출처 4 × 사전 라벨 4 = 16칸, 칸마다 per_cell 건 (기본 38 → 약 600건). rows 를 주면 DB 대신 그것을 씀(시험용)."""
    if rows is None:
        from . import db

        rows = db.q(SAMPLE_SQL, {"seed": seed, "sources": list(SOURCES), "as_of": as_of, "per_cell": per_cell})
    path = Path(path)
    fields = [x for x in FIELDS if not (blind and x in BLIND_DROP)]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:  # 엑셀에서 한글이 깨지지 않게 BOM
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**{k: "" for k in fields}, **{k: r.get(k) for k in fields if k in r}})
    return path


def _norm(x) -> str | None:
    x = str(x or "").strip().lower()
    aliases = {"neg": "negative", "부정": "negative", "pos": "positive", "긍정": "positive", "neu": "neutral",
               "중립": "neutral", "무관": "irrelevant", "irr": "irrelevant"}
    x = aliases.get(x, x)
    return x if x in GOLD else None


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x and y]
    n = len(pairs)
    if not n:
        return None
    po = sum(x == y for x, y in pairs) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return None if pe == 1 else (po - pe) / (1 - pe)


def macro_f1(gold: list[str], pred: list[str], labels=LABELS) -> float | None:
    f1s = []
    for lab in labels:
        tp = sum(g == lab and p == lab for g, p in zip(gold, pred))
        fp = sum(g != lab and p == lab for g, p in zip(gold, pred))
        fn = sum(g == lab and p != lab for g, p in zip(gold, pred))
        if tp + fp + fn == 0:
            continue
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec))
    return sum(f1s) / len(f1s) if f1s else None


def score(rows: list[dict], pred_field: str = "dict_label") -> dict:
    """라벨된 행으로 채점. 정답: label_final 이 있으면 그것, 없으면 두 라벨러가 같을 때만 그 값.
    사전 라벨 'none'(키워드 없음)은 neutral 로 예측한 것으로 보고 따로 비율을 셉니다."""
    a = [_norm(r.get("label_a")) for r in rows]
    b = [_norm(r.get("label_b")) for r in rows]
    out: dict = {"n_rows": len(rows), "n_double": sum(1 for x, y in zip(a, b) if x and y), "kappa": cohen_kappa(a, b)}
    gold, pred, src, none = [], [], [], 0
    for r, x, y in zip(rows, a, b):
        g = _norm(r.get("label_final")) or (x if x and x == y else None)
        if g is None:
            continue
        p = str(r.get(pred_field) or "none").strip().lower()
        none += p == "none"
        gold.append(g)
        pred.append("neutral" if p == "none" else p)
        src.append(r.get("source"))
    rel = [(g, p, s) for g, p, s in zip(gold, pred, src) if g != "irrelevant"]
    out.update({
        "n_gold": len(gold), "irrelevant_share": (sum(g == "irrelevant" for g in gold) / len(gold) * 100) if gold else None,
        "dict_none_share": (none / len(gold) * 100) if gold else None,
        "accuracy": (sum(g == p for g, p, _ in rel) / len(rel) * 100) if rel else None,
        "macro_f1": macro_f1([g for g, _, _ in rel], [p for _, p, _ in rel]),
        "confusion": {g: dict(Counter(p for gg, p, _ in rel if gg == g)) for g in LABELS},
        "by_source": {},
    })
    for s in sorted({s for _, _, s in rel if s}):
        sub = [(g, p) for g, p, ss in rel if ss == s]
        out["by_source"][s] = {"n": len(sub), "accuracy": sum(g == p for g, p in sub) / len(sub) * 100,
                               "macro_f1": macro_f1([g for g, _ in sub], [p for _, p in sub])}
    out["adoption_rule"] = "새 감성 모델은 매크로 F1 이 사전 대비 0.05 이상 높을 때만 교체 (P03 15장)"
    return out


def load(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def merge_dict_labels(labeled: list[dict], full: list[dict]) -> list[dict]:
    """눈가림(blind) 파일에 라벨을 단 뒤, 사전 라벨이 있는 원본과 doc_id 로 합칩니다."""
    by = {str(r["doc_id"]): r for r in full}
    return [{**by.get(str(r["doc_id"]), {}), **{k: v for k, v in r.items() if v not in (None, "")}} for r in labeled]
