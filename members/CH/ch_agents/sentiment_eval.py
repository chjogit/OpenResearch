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


# ======================================================================================================
# #39 감성 평가셋 (3인 라벨러 JT·SH·CH → 결과에는 A·B·C, 최종 확인 SW). 안내서: .scratch/data-gaps/sentiment-labeling-guide.md
#  sample_rows()  메인(뉴스·해외뉴스·유튜브 댓글)과 kic-opinion(블로그·카페)을 읽기 전용으로 읽어 출처 × 사전 구간 × 종목으로 층화 추출
#  build_sheets() 라벨러별 시트(xlsx, 같은 문서·순서 섞음, 사전 점수 없음) + 표본 원문 보존 파일(sample_full.csv) + 메타(sample_meta.json)
#  score3()       회수한 시트로 Fleiss·쌍별 Cohen kappa, 다수결 정답, SW 확인 목록, 사전 감성 성능
# 결과 파일에는 문서 제목·요약이 들어 있으므로 커밋하지 않습니다 (.gitignore: members/CH/eval_sets/).
# ======================================================================================================
import hashlib
import json
import os
import random

SHEET_LABELS = ("긍정", "중립", "부정", "무관")
KO_EN = {"긍정": "positive", "중립": "neutral", "부정": "negative", "무관": "irrelevant"}
YESNO = ("예", "아니오")
SOURCE_KO = {"naver_news": "뉴스", "finnhub_news": "해외뉴스", "naver_blog": "블로그", "naver_cafe": "카페", "youtube_comment": "유튜브 댓글"}
QUOTAS = {"naver_news": 150, "finnhub_news": 60, "naver_blog": 150, "naver_cafe": 120, "youtube_comment": 120}   # 합 600
OPINION_SOURCES = ("naver_blog", "naver_cafe")        # kic-opinion 에 있는 출처 (나머지는 메인)
DICT_CELLS = ("positive", "neutral", "negative", "none")
LABELERS = ("A", "B", "C")
SHEET_COLS = ["id", "종목", "출처", "날짜", "제목", "요약", "링크", "감성", "불확실성", "메모"]

SAMPLE3_SQL = """
WITH r AS (
    SELECT d.doc_id, d.company_id, d.source, d.published_at, d.title, left(coalesce(d.summary, ''), 400) AS summary, d.url,
           coalesce(s.label, 'none') AS dict_label, s.score AS dict_score,
           row_number() OVER (PARTITION BY coalesce(s.label, 'none'), d.company_id ORDER BY md5(d.doc_id::text || %(seed)s)) AS rk
    FROM rag.document d LEFT JOIN core.doc_sentiment s USING (doc_id)
    WHERE d.source = %(source)s AND d.published_at <= %(as_of)s::date
      AND length(coalesce(d.title, '') || coalesce(d.summary, '')) >= 20 AND d.company_id IS NOT NULL
)
SELECT * FROM r WHERE dict_label = %(label)s ORDER BY rk, md5(doc_id::text || %(seed)s) LIMIT %(n)s
"""


def _read(url: str, sql: str, params: dict) -> list[dict]:
    """읽기 전용 조회 (메인 db.q 와 같은 방식, 접속 문자열만 다름)."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(url, row_factory=dict_row, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = on")
        conn.execute("SET statement_timeout = '60s'")
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def split_quota(total: int, cells: tuple = DICT_CELLS) -> dict:
    base, extra = divmod(total, len(cells))
    return {c: base + (1 if i < extra else 0) for i, c in enumerate(cells)}


def _dup_key(r: dict) -> str:
    """같은 글 판정: 제목 + 요약 앞부분 (유튜브 댓글은 영상 제목이 같고 댓글 본문이 요약이라 제목만으로는 구분 안 됨)."""
    return f"{(r.get('title') or '').strip()}|{(r.get('summary') or '').strip()[:80]}"


def pick_rows(fetch, total: int, seed: str) -> list[dict]:
    """한 출처에서 total 건: 사전 구간(긍정·중립·부정·점수 없음)에 균등 배분하고 부족한 칸은 다른 칸이 채움. 같은 제목은 한 번만.
    fetch(label, n) → 후보 행(종목이 고르게 앞서도록 정렬됨)."""
    quota = split_quota(total)
    got: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for lab in DICT_CELLS:
        rows = []
        for r in fetch(lab, quota[lab] * 3):
            key = _dup_key(r)
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)
            if len(rows) >= quota[lab]:
                break
        got[lab] = rows
    short = total - sum(len(v) for v in got.values())
    for lab in sorted(DICT_CELLS, key=lambda x: -len(got[x])):          # 부족분은 여유 있는 칸에서 더 뽑음
        if short <= 0:
            break
        for r in fetch(lab, quota[lab] * 3 + short * 3):
            key = _dup_key(r)
            if key in seen:
                continue
            seen.add(key)
            got[lab].append(r)
            short -= 1
            if short <= 0:
                break
    return [r for lab in DICT_CELLS for r in got[lab]]


def sample_rows(as_of: str, seed: str = "p03-evalset-v1", quotas: dict | None = None) -> list[dict]:
    """메인·kic-opinion 에서 약 600건. 종목 이름은 메인 core.company 로 붙임(kic-opinion 은 company_id 만 같음)."""
    from . import db

    main_url, op_url = db.database_url(), os.getenv("OPINION_DATABASE_URL", "")
    if not op_url:
        raise RuntimeError("OPINION_DATABASE_URL 이 비어 있습니다 (블로그·카페는 kic-opinion 에 있음).")
    companies = {r["company_id"]: r for r in db.q("SELECT company_id, market, ticker, name FROM core.company", {})}
    out: list[dict] = []
    for source, total in (quotas or QUOTAS).items():
        url = op_url if source in OPINION_SOURCES else main_url

        def fetch(lab, n, source=source, url=url):
            return _read(url, SAMPLE3_SQL, {"seed": seed, "source": source, "as_of": as_of, "label": lab, "n": n})

        for r in pick_rows(fetch, total, seed):
            c = companies.get(r["company_id"], {})
            out.append({**r, "ticker": c.get("ticker"), "name": c.get("name"), "market": c.get("market"),
                        "published_at": str(r["published_at"])[:10], "dict_score": None if r["dict_score"] is None else float(r["dict_score"])})
    return out


def _sheet_rows(rows: list[dict], labeler: str, seed: str) -> list[dict]:
    """같은 문서 전부, 순서는 라벨러마다 다르게(재현 가능). 사전 점수·라벨은 넣지 않음."""
    order = sorted(rows, key=lambda r: hashlib.md5(f"{seed}|{labeler}|{r['doc_id']}".encode()).hexdigest())
    return [{"id": r["doc_id"], "종목": f"{r.get('name') or ''}({r.get('ticker') or ''})", "출처": SOURCE_KO.get(r["source"], r["source"]),
             "날짜": r["published_at"], "제목": r.get("title") or "", "요약": r.get("summary") or "", "링크": r.get("url") or "",
             "감성": "", "불확실성": "", "메모": ""} for r in order]


def write_sheet(path, sheet_rows: list[dict]) -> None:
    """라벨러용 xlsx: 감성·불확실성은 드롭다운, id~링크 열은 잠그지 않되 폭만 맞춤."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "라벨"
    ws.append(SHEET_COLS)
    for r in sheet_rows:
        ws.append([r[c] for c in SHEET_COLS])
    n = len(sheet_rows) + 1
    dv1 = DataValidation(type="list", formula1='"' + ",".join(SHEET_LABELS) + '"', allow_blank=True)
    dv2 = DataValidation(type="list", formula1='"' + ",".join(YESNO) + '"', allow_blank=True)
    ws.add_data_validation(dv1)
    ws.add_data_validation(dv2)
    dv1.add(f"H2:H{n}")
    dv2.add(f"I2:I{n}")
    for col, w in zip("ABCDEFGHIJ", (9, 18, 9, 11, 48, 70, 30, 9, 9, 28)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2, max_row=n, min_col=5, max_col=6):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    wb.save(path)


def build_sheets(rows: list[dict], out_dir, as_of: str, seed: str = "p03-evalset-v1") -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for lab in LABELERS:
        write_sheet(out / f"labeler_{lab}.xlsx", _sheet_rows(rows, lab, seed))
    with (out / "sample_full.csv").open("w", encoding="utf-8-sig", newline="") as fh:     # 원문 보존 + 사전 점수(채점용, 라벨러에게 주지 않음)
        cols = ["doc_id", "source", "ticker", "name", "published_at", "title", "summary", "url", "dict_label", "dict_score"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    meta = {"as_of": as_of, "seed": seed, "n": len(rows), "quotas": QUOTAS, "labelers": list(LABELERS),
            "by_source": dict(Counter(r["source"] for r in rows)), "by_dict_label": dict(Counter(r["dict_label"] for r in rows)),
            "tickers": len({r.get("ticker") for r in rows}), "date_min": min(r["published_at"] for r in rows),
            "date_max": max(r["published_at"] for r in rows),
            "method": "출처별 쿼터 × 사전 구간(긍정·중립·부정·점수 없음) 균등 × 종목 라운드로빈(해시 순서), 같은 제목 제외, 제목+요약 20자 미만 제외"}
    (out / "sample_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def read_sheet(path) -> dict[str, dict]:
    """회수한 시트(xlsx 또는 csv) → {id: {감성, 불확실성, 메모}}. 감성은 영문/한글 모두 받아 한글로 통일, 못 읽으면 빈칸."""
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook

        ws = load_workbook(path, read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        head = [str(x or "").strip() for x in next(it)]
        recs = [dict(zip(head, row)) for row in it]
    else:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            recs = list(csv.DictReader(fh))
    en_ko = {v: k for k, v in KO_EN.items()}
    out = {}
    for r in recs:
        if r.get("id") in (None, ""):
            continue
        lab = str(r.get("감성") or "").strip()
        lab = lab if lab in SHEET_LABELS else en_ko.get(lab.lower(), "")
        unc = str(r.get("불확실성") or "").strip()
        out[str(int(float(r["id"])))] = {"감성": lab, "불확실성": unc if unc in YESNO else "", "메모": str(r.get("메모") or "")}
    return out


def fleiss_kappa(items: list[list[str]], cats=SHEET_LABELS) -> float | None:
    """items: 문서마다 라벨러 수가 같은 라벨 목록(빈칸 있는 문서는 미리 제외). 일치만 있고 변동이 없으면 None."""
    n = len(items[0]) if items else 0
    if not items or n < 2:
        return None
    counts = [Counter(x) for x in items]
    p_bar = sum((sum(c[k] ** 2 for k in cats) - n) / (n * (n - 1)) for c in counts) / len(items)
    pj = [sum(c[k] for c in counts) / (len(items) * n) for k in cats]
    pe = sum(p * p for p in pj)
    return None if pe == 1 else (p_bar - pe) / (1 - pe)


def decide(votes: list[str]) -> dict:
    """세 라벨 → 다수결 정답. SW 확인 대상: 셋 다 다르거나, '무관'과 그 밖의 값이 섞인 경우(대상 기업 매핑 품질 문제)."""
    c = Counter(v for v in votes if v)
    top, k = c.most_common(1)[0] if c else (None, 0)
    mixed_irrelevant = "무관" in c and len(c) > 1
    needs_sw = len(votes) == 3 and (len(c) == 3 or mixed_irrelevant)
    return {"majority": top if k >= 2 else None, "needs_sw": needs_sw}


def _prf(gold: list[str], pred: list[str], cats=("긍정", "중립", "부정")) -> dict:
    out = {}
    for k in cats:
        tp = sum(g == k and p == k for g, p in zip(gold, pred))
        fp = sum(g != k and p == k for g, p in zip(gold, pred))
        fn = sum(g == k and p != k for g, p in zip(gold, pred))
        pr, rc = tp / (tp + fp) if tp + fp else None, tp / (tp + fn) if tp + fn else None
        out[k] = {"precision": pr, "recall": rc, "n_gold": tp + fn,
                  "f1": None if not pr or not rc else 2 * pr * rc / (pr + rc)}
    return out


def _find_returned(d: Path, lab: str):
    """returned/ 에서 라벨러 파일 찾기: labeler_A.xlsx 또는 labeler_A_labeled_v3.xlsx 등. 여러 버전이면 가장 큰 _vN, 없으면 이름순 마지막. 원본은 고치지 않음."""
    import re

    cands = [f for f in (d / "returned").glob(f"labeler_{lab}*") if f.suffix.lower() in (".xlsx", ".csv")]
    ver = lambda f: (int(m.group(1)) if (m := re.search(r"_v(\d+)", f.stem)) else -1, f.suffix.lower() == ".xlsx", f.name)   # noqa: E731
    return max(cands, key=ver) if cands else None


def _raw_issues(path) -> dict:
    """시트의 허용 밖 값 수(감성·불확실성 칸에 값이 있는데 선택지가 아닌 것; 영문 감성 표기는 허용)."""
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook

        it = load_workbook(path, read_only=True, data_only=True).active.iter_rows(values_only=True)
        head = [str(x or "").strip() for x in next(it)]
        recs = [dict(zip(head, row)) for row in it]
    else:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            recs = list(csv.DictReader(fh))
    en_ko = {v: k for k, v in KO_EN.items()}
    bad_s = bad_u = 0
    for r in recs:
        if r.get("id") in (None, ""):
            continue
        a, b = str(r.get("감성") or "").strip(), str(r.get("불확실성") or "").strip()
        bad_s += bool(a) and a not in SHEET_LABELS and a.lower() not in en_ko
        bad_u += bool(b) and b not in YESNO
    return {"invalid_sentiment": bad_s, "invalid_uncertainty": bad_u}


def score3(sheet_dir, out_dir=None) -> dict:
    """sheet_dir/returned/labeler_{A,B,C}.(xlsx|csv) 와 sample_full.csv(, sw_resolved.csv: id,감성)로 채점. out_dir 에 SW 확인 목록·정답표 저장."""
    d = Path(sheet_dir)
    full = {str(r["doc_id"]): r for r in load(d / "sample_full.csv")}
    sheets, files, issues = {}, {}, {}
    for lab in LABELERS:
        f = _find_returned(d, lab)
        if f is None:
            raise FileNotFoundError(f"{d / 'returned'} 에 labeler_{lab}.xlsx(또는 csv) 가 없습니다.")
        sheets[lab] = read_sheet(f)
        files[lab] = f.name
        issues[lab] = {**_raw_issues(f), "n_rows": len(sheets[lab]), "ids_missing_vs_sample": sum(1 for i in full if i not in sheets[lab]),
                       "ids_not_in_sample": sum(1 for i in sheets[lab] if i not in full)}
    ids = [i for i in full if all(i in sheets[l] for l in LABELERS)]
    complete = [i for i in ids if all(sheets[l][i]["감성"] for l in LABELERS)]
    out: dict = {"files": files, "sheet_checks": issues, "n_sample": len(full), "n_complete_3": len(complete), "labeler_blank": {l: sum(1 for i in ids if not sheets[l][i]["감성"]) for l in LABELERS}}
    out["kappa_sentiment_fleiss"] = fleiss_kappa([[sheets[l][i]["감성"] for l in LABELERS] for i in complete])
    out["kappa_sentiment_pairs"] = {f"{a}{b}": cohen_kappa([sheets[a][i]["감성"] for i in complete], [sheets[b][i]["감성"] for i in complete])
                                     for a, b in (("A", "B"), ("A", "C"), ("B", "C"))}
    unc = [i for i in ids if all(sheets[l][i]["불확실성"] for l in LABELERS)]
    out["kappa_uncertainty_fleiss"] = fleiss_kappa([[sheets[l][i]["불확실성"] for l in LABELERS] for i in unc], cats=YESNO)
    out["kappa_uncertainty_pairs"] = {f"{a}{b}": cohen_kappa([sheets[a][i]["불확실성"] for i in unc], [sheets[b][i]["불확실성"] for i in unc])
                                       for a, b in (("A", "B"), ("A", "C"), ("B", "C"))}
    sw_done = {}
    p = d / "sw_resolved.csv"
    if p.exists():
        sw_done = {str(int(float(r["id"]))): r["감성"].strip() for r in load(p) if r.get("감성", "").strip() in SHEET_LABELS}
    gold, sw_list = {}, []
    for i in complete:
        dec = decide([sheets[l][i]["감성"] for l in LABELERS])
        if dec["needs_sw"]:
            if i in sw_done:
                gold[i] = sw_done[i]
            else:
                sw_list.append(i)
        elif dec["majority"]:
            gold[i] = dec["majority"]
    out.update({"n_gold": len(gold), "n_sw_pending": len(sw_list), "n_sw_resolved": sum(1 for i in complete if i in sw_done)})
    if out_dir is not None:
        o = Path(out_dir)
        o.mkdir(parents=True, exist_ok=True)
        with (o / "sw_check_list.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "종목", "출처", "제목", "요약", "링크", "A", "B", "C", "감성(SW 확인)"])
            for i in sw_list:
                r = full[i]
                w.writerow([i, f"{r.get('name')}({r.get('ticker')})", SOURCE_KO.get(r["source"], r["source"]), r["title"], r["summary"], r["url"],
                            *[sheets[l][i]["감성"] for l in LABELERS], ""])
    rel = [i for i in gold if gold[i] != "무관"]
    pred = {i: {"positive": "긍정", "negative": "부정", "neutral": "중립", "none": "중립"}.get(str(full[i].get("dict_label") or "none"), "중립") for i in gold}
    g, pr = [gold[i] for i in rel], [pred[i] for i in rel]
    out.update({
        "irrelevant_share": (sum(v == "무관" for v in gold.values()) / len(gold) * 100) if gold else None,
        "irrelevant_by_source": {s: round(sum(gold[i] == "무관" for i in gold if full[i]["source"] == s) / max(1, sum(1 for i in gold if full[i]["source"] == s)) * 100, 1)
                                 for s in sorted({full[i]["source"] for i in gold})},
        "dict_none_share": (sum(str(full[i].get("dict_label")) == "none" for i in gold) / len(gold) * 100) if gold else None,
        "n_eval": len(rel), "accuracy": (sum(a == b for a, b in zip(g, pr)) / len(g) * 100) if g else None,
        "per_class": _prf(g, pr), "confusion(정답→사전)": {k: dict(Counter(p for a, p in zip(g, pr) if a == k)) for k in ("긍정", "중립", "부정")},
        "by_source": {s: {"n": len(sub), "accuracy": sum(a == b for a, b in sub) / len(sub) * 100}
                      for s in sorted({full[i]["source"] for i in rel}) for sub in [[(gold[i], pred[i]) for i in rel if full[i]["source"] == s]]},
        "gate": "Fleiss kappa 0.6 이상이면 정답으로 사용, 낮으면 규칙 보완 후 일부 재라벨 (안내서 7장)",
    })
    if out_dir is not None:
        with (Path(out_dir) / "gold.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "정답", "A", "B", "C", "사전"])
            for i, v in gold.items():
                w.writerow([i, v, *[sheets[l][i]["감성"] for l in LABELERS], pred[i]])
    return out
