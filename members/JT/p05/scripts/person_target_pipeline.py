"""대주주·CEO 대상 감성분석 파이프라인.

분석 단위: 문장 × 대상 인물/집단 × 사건 1개
라벨: 대상 사건의 주주 영향 positive / neutral / negative, 판단 불가는 HOLD
- 인물의 성격·호감도는 평가하지 않는다.
- 기업 단위 라벨(gov_dev_set.csv의 label)을 사람 정답으로 쓰지 않는다.
- gov_challenge_set.csv는 이 모듈 어디에서도 읽지 않는다.
- 범위: 출처가 명확한 행만 만든다(2026-10-28 기준 강화).
  · 대상 이름이 DART 명부(대주주·CEO)의 이름과 그대로 일치할 것(약칭·성·역할어 연결은 쓰지 않는다)
  · 기사 게시일을 URL에서 확인하거나, 네이버 검색 API의 게시일(seed의 published_at)로 확인할 수 있을 것
  · 게시일이 명부 근거 기간(2026 반기보고서 대상 기간 시작일) 이후이고 기준일 이전일 것
"""
from pathlib import Path
import hashlib
import json
import re

import numpy as np
import pandas as pd

LABELS = ["negative", "neutral", "positive"]
ALL_DECISIONS = LABELS + ["HOLD"]
HOLDOUT_SALT = "person-target-20261027"   # 회사 분할 해시 소금값(사전 고정, 바꾸지 않는다)
HOLDOUT_PCT = 35                          # 회사의 약 35%를 잠금 점검 세트로 보낸다(사전 고정)
# 데이터에 남기는 연결 상태: 명부 이름과 정확히 일치한 경우만
IN_SCOPE = {"LINKED_DART"}
# 명부 근거(2026 반기보고서)가 다루는 기간의 시작일. 이보다 오래된 기사는 당시 역할을 확인할 근거가 없다
ROSTER_PERIOD_START = "2026-01-01"
MODEL_NAME = "snunlp/KR-FinBert-SC"


# ---------------------------------------------------------------------------
# 1. 출처 정리
# ---------------------------------------------------------------------------
def event_date_from_url(url):
    """URL 안의 날짜(YYYY/MM/DD 또는 YYYYMMDD)를 찾는다. 확인 못 하면 빈칸으로 둔다."""
    for m in re.finditer(r"(20[12]\d)[/-]?(\d{2})[/-]?(\d{2})", str(url)):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2015 <= y <= 2026 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return ""


# ---------------------------------------------------------------------------
# 2. 대상 연결: 기사 제목 속 이름 → DART 명부
# ---------------------------------------------------------------------------
def link_targets(news, roster, as_of="2026-10-27"):
    """뉴스 1건에서 대주주·CEO 대상 행만 만든다. 출처가 불분명한 행은 만들지 않는다."""
    rows = []
    for _, n in news.iterrows():
        comp = roster.loc[roster["company_name"] == n["company_name"]]
        # 같은 사람이 CEO·주요주주로 두 번 있으면 역할을 합친다(CEO 행을 대표 근거로 사용)
        comp = comp.sort_values("role", key=lambda s: s.ne("CEO/대표이사"))
        people = comp.groupby("canonical_name", sort=False).agg(
            person_id=("person_id", "first"), role=("role", lambda s: "|".join(dict.fromkeys(s))),
            rcept_no=("rcept_no", "first"), roster_as_of=("as_of", "first"),
            verification_status=("verification_status", "first"))
        title = n["source_title"]
        found = []

        # (1) 명부 이름이 제목에 그대로 있는 경우 → 연결
        for name, p in people.iterrows():
            if name in title:
                found.append((name, p, "exact_name", "LINKED_DART"))
        # 게시일: 네이버 검색 API가 준 게시일(published_at)이 있으면 그것을, 없으면 URL 속 날짜를 쓴다
        api_date = str(n.get("published_at", ""))[:10]
        event_date = api_date or event_date_from_url(n["source_url"])
        for name, p, method, status in found:
            rows.append({
                "news_id": n["news_id"], "company_name": n["company_name"],
                "event_date": event_date, "date_status": "DATE_FROM_API" if api_date else "DATE_FROM_URL",
                "source_type": n["source_type"], "source_url": n["source_url"],
                "source_title": title, "text_original": title,
                "target_name": name, "target_id": p["person_id"],
                "target_role": p["role"],
                "link_method": method, "link_status": status,
                "roster_rcept_no": p["rcept_no"], "roster_as_of": p["roster_as_of"],
                "roster_verification": p["verification_status"],
                "as_of": as_of,
            })
    out = pd.DataFrame(rows)
    out = out.loc[out["link_status"].isin(IN_SCOPE)]
    # 게시일을 모르는 기사, 명부 근거 기간보다 오래된 기사, 기준일 이후 기사(미래정보)는 뺀다
    dated = out["event_date"].ne("") & out["event_date"].ge(ROSTER_PERIOD_START) & out["event_date"].le(as_of)
    out = out.loc[dated].reset_index(drop=True)
    out.insert(0, "row_id", [f"PT2-{i:04d}" for i in range(1, len(out) + 1)])
    return out


# ---------------------------------------------------------------------------
# 3. 회사 그룹 분할 (주석 전에 고정)
# ---------------------------------------------------------------------------
def assign_company_split(companies, salt=HOLDOUT_SALT, holdout_pct=HOLDOUT_PCT):
    """회사 이름의 해시로 dev/holdout을 정한다. 같은 회사는 한쪽에만 들어간다.
    해시 방식이라 나중에 회사를 추가해도 기존 회사의 배정이 바뀌지 않는다."""
    def bucket(c):
        return int(hashlib.sha256(f"{salt}|{c}".encode("utf-8")).hexdigest(), 16) % 100
    return {c: ("holdout" if bucket(c) < holdout_pct else "dev") for c in sorted(set(companies))}


def sha256_of(df, cols):
    """잠금 확인용 해시. 지정 열의 내용이 한 글자라도 바뀌면 값이 달라진다."""
    payload = df[cols].astype(str).to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# 4. 두 명 독립 주석지와 합의
# ---------------------------------------------------------------------------
ANNOTATOR_VIEW = ["row_id", "company_name", "event_date", "source_url", "text_original",
                  "target_name", "target_role", "link_status"]
ANNOTATOR_FILL = ["target_clause", "event_type", "person_impact_label", "review_status",
                  "hold_reason", "annotator_id", "annotation_note"]


def write_annotation_sheets(targets, out_dir):
    """주석자 A·B용 빈 시트를 만든다. 사람이 채운 파일이 있으면 절대 덮어쓰지 않는다.
    기존 시트가 있으면 기존 행(채운 내용 포함)은 그대로 두고, 새로 생긴 row_id만 끝에 덧붙인다.
    모델 예측·기업 라벨은 시트에 넣지 않는다(독립성·편향 방지)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for split in ["dev", "holdout"]:
        part = targets.loc[targets["split"] == split, ANNOTATOR_VIEW].copy()
        for col in ANNOTATOR_FILL:
            part[col] = ""
        for annot in ["A", "B"]:
            path = out_dir / f"annotator_{annot}_{split}.csv"
            seed = 1 if annot == "A" else 2   # 주석자마다 행 순서를 다르게 섞어 순서 효과를 줄인다
            if path.exists():
                old = pd.read_csv(path, dtype=str).fillna("")
                add = part.loc[~part["row_id"].isin(old["row_id"])]
                if add.empty:
                    written.append((path.name, "기존 파일 보존(새 행 없음)"))
                    continue
                pd.concat([old, add.sample(frac=1, random_state=seed)], ignore_index=True)[old.columns] \
                  .to_csv(path, index=False, encoding="utf-8-sig")
                written.append((path.name, f"기존 {len(old)}행 보존 + 새 {len(add)}행 추가"))
                continue
            part.sample(frac=1, random_state=seed).to_csv(path, index=False, encoding="utf-8-sig")
            written.append((path.name, f"{len(part)}행 생성"))
    return written


EVENT_TYPES = ["지분취득", "지분처분", "증여·상속", "담보", "선임·연임", "교체·사임", "보수·보상", "수사·재판",
               "경영권분쟁", "주주환원결정", "발언·전략", "투자·M&A", "세금·재원", "행사·IR", "기타"]
HOLD_REASONS = ["target_unclear", "target_link_wrong", "insufficient_evidence", "mixed", "out_of_scope",
                "date_or_role_mismatch"]


def check_sheet(path, candidates_path):
    """주석 시트가 규약 형식을 지키는지 검사한다. 라벨이 맞는지는 판단하지 않는다(형식만 본다).
    돌려주는 값: (문제 목록 DataFrame, 요약 dict). 문제 목록이 비면 제출해도 된다."""
    sheet = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    cand = pd.read_csv(candidates_path, dtype=str, encoding="utf-8-sig").fillna("").set_index("row_id")
    issues = []
    def add(r, msg): issues.append({"row_id": r["row_id"], "problem": msg})
    for _, r in sheet.iterrows():
        # 주석자가 보기 전용 열을 바꾸지 않았는지
        c = cand.loc[r["row_id"]] if r["row_id"] in cand.index else None
        if c is None or c["text_original"] != r["text_original"] or c["target_name"] != r["target_name"]:
            add(r, "보기 전용 열(text_original/target_name)이 원본과 다름"); continue
        status = r["review_status"].strip().upper()
        if not status and not r["person_impact_label"]:
            continue   # 아직 안 한 행. 아래 요약에서 센다
        if status not in ("LABEL", "HOLD"):
            add(r, "review_status는 LABEL 또는 HOLD")
        if status == "LABEL" and r["person_impact_label"].strip().lower() not in LABELS:
            add(r, "LABEL이면 person_impact_label은 positive/neutral/negative")
        if status == "HOLD" and (r["person_impact_label"] or r["hold_reason"] not in HOLD_REASONS):
            add(r, "HOLD면 person_impact_label은 비우고 hold_reason은 규약 3절 코드")
        if r["event_type"] not in EVENT_TYPES:
            add(r, "event_type이 규약 4절 목록에 없음")
        if not r["target_clause"] or r["target_clause"] not in r["text_original"]:
            add(r, "target_clause는 원문에서 그대로 복사한 구절이어야 함")
        if not r["annotator_id"] or not r["annotation_note"]:
            add(r, "annotator_id와 annotation_note(판단 근거 한 줄)가 필요함")
    done = sheet["review_status"].ne("") | sheet["person_impact_label"].ne("")
    summary = {"rows": int(len(sheet)), "done": int(done.sum()), "todo": int((~done).sum()), "issues": len(issues)}
    return pd.DataFrame(issues, columns=["row_id", "problem"]), summary


def _decision(row):
    """주석 한 행을 최종 판정 하나로 바꾼다. HOLD면 감성 라벨보다 우선한다."""
    if str(row.get("review_status", "")).upper() == "HOLD":
        return "HOLD"
    lab = str(row.get("person_impact_label", "")).strip().lower()
    return lab if lab in LABELS else ""


def cohen_kappa(a, b, labels=ALL_DECISIONS):
    """Cohen's kappa = (관찰 일치율 - 우연 일치율) / (1 - 우연 일치율)."""
    from sklearn.metrics import cohen_kappa_score
    return float(cohen_kappa_score(a, b, labels=labels))


def compare_annotators(path_a, path_b):
    """A·B 시트를 합쳐 일치도와 불일치 목록을 만든다. 둘 다 끝난 행만 계산한다."""
    a = pd.read_csv(path_a, encoding="utf-8-sig", dtype=str).fillna("")
    b = pd.read_csv(path_b, encoding="utf-8-sig", dtype=str).fillna("")
    m = a.merge(b, on="row_id", suffixes=("_A", "_B"))
    m["decision_A"] = m.filter(like="_A").rename(columns=lambda c: c[:-2]).apply(_decision, axis=1)
    m["decision_B"] = m.filter(like="_B").rename(columns=lambda c: c[:-2]).apply(_decision, axis=1)
    done = m.loc[m["decision_A"].ne("") & m["decision_B"].ne("")]
    report = {"rows_total": int(len(m)), "rows_both_done": int(len(done))}
    if len(done):
        report["percent_agreement"] = float((done["decision_A"] == done["decision_B"]).mean())
        report["kappa_4way_incl_HOLD"] = cohen_kappa(done["decision_A"], done["decision_B"])
        both3 = done.loc[done["decision_A"].isin(LABELS) & done["decision_B"].isin(LABELS)]
        if len(both3) >= 2:
            report["kappa_3way_both_labeled"] = cohen_kappa(both3["decision_A"], both3["decision_B"], LABELS)
            report["rows_both_labeled"] = int(len(both3))
    disagree = done.loc[done["decision_A"] != done["decision_B"],
                        ["row_id", "decision_A", "decision_B", "annotation_note_A", "annotation_note_B"]].copy()
    disagree["adjudicated_decision"] = ""
    disagree["adjudication_reason"] = ""
    return m, report, disagree


def finalize_labels(merged, adjudication=None):
    """일치 행은 그대로, 불일치 행은 합의 결과를 쓴다. 합의가 빈 행이 있으면 최종 라벨을 만들지 않는다."""
    out = merged[["row_id", "decision_A", "decision_B"]].copy()
    out["final_decision"] = np.where(out["decision_A"] == out["decision_B"], out["decision_A"], "")
    if adjudication is not None:
        adj = adjudication.set_index("row_id")["adjudicated_decision"].to_dict()
        out["final_decision"] = [fd or adj.get(r, "") for r, fd in zip(out["row_id"], out["final_decision"])]
    missing = int(out["final_decision"].eq("").sum())
    if missing:
        raise ValueError(f"최종 판정이 빈 행 {missing}개: 주석 또는 합의를 먼저 끝내세요.")
    bad = set(out["final_decision"]) - set(ALL_DECISIONS)
    if bad:
        raise ValueError(f"허용되지 않은 판정값: {bad}")
    return out


# ---------------------------------------------------------------------------
# 5. 공개 모델 기준선 (가중치 학습 없음)
# ---------------------------------------------------------------------------
def build_input(row, variant):
    """variant='text': 원문만 / 'marked': 대상 역할·이름 표식 + 원문.
    표식은 모델에게 '누구에 대한 문장인지'를 알려 주려는 시도이며, 공개 모델은 이 표식으로 학습되지 않았다."""
    if variant == "text":
        return row["text_original"]
    name = row["target_name"] or "미상"
    role = row["target_role"] or "미상"
    return f"[대상 역할: {role}] [대상: {name}] {row['text_original']}"


def predict_proba(texts, model_name=MODEL_NAME, batch_size=16):
    """KR-FinBert-SC 확률을 LABELS 순서(negative, neutral, positive)로 돌려준다."""
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name).eval()
    id2label = {i: l.lower() for i, l in model.config.id2label.items()}
    order = [next(i for i, l in id2label.items() if l == lab) for lab in LABELS]
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            enc = tok(list(texts[i:i + batch_size]), padding=True, truncation=True, max_length=128, return_tensors="pt")
            out.append(torch.softmax(model(**enc).logits, dim=-1)[:, order].numpy())
    return np.vstack(out) if out else np.zeros((0, 3))


def decide(proba, tau):
    """최고 확률이 tau 미만이면 HOLD, 아니면 최고 확률 라벨."""
    lab = np.array(LABELS)[proba.argmax(1)]
    return np.where(proba.max(1) < tau, "HOLD", lab)


# ---------------------------------------------------------------------------
# 6. 평가 지표
# ---------------------------------------------------------------------------
def evaluate(gold, pred, companies):
    """정답 HOLD 행은 감성 지표에서 빼고 따로 센다.
    macro-F1(strict): 모델이 HOLD로 미룬 행은 틀린 것으로 본다(보류를 공짜로 만들지 않기 위해).
    보류율: 정답이 감성 라벨인 행 중 모델이 HOLD로 미룬 비율."""
    from sklearn.metrics import f1_score, precision_recall_fscore_support, confusion_matrix
    gold, pred, companies = np.asarray(gold), np.asarray(pred), np.asarray(companies)
    lab = np.isin(gold, LABELS)
    g, p, c = gold[lab], pred[lab], companies[lab]
    res = {"n_rows": int(len(gold)), "n_gold_hold": int((~lab).sum()), "n_gold_labeled": int(lab.sum())}
    if lab.sum() == 0:
        return res
    pr, rc, f1, sup = precision_recall_fscore_support(g, p, labels=LABELS, zero_division=0)
    decided = p != "HOLD"
    res.update({
        "macro_f1_strict": float(f1_score(g, p, labels=LABELS, average="macro", zero_division=0)),
        "per_class": {l: {"precision": float(pr[i]), "recall": float(rc[i]), "f1": float(f1[i]), "support": int(sup[i])}
                      for i, l in enumerate(LABELS)},
        "hold_rate": float((~decided).mean()),
        "coverage": float(decided.mean()),
        "selective_accuracy": float((g[decided] == p[decided]).mean()) if decided.any() else None,
        "confusion_labels": ALL_DECISIONS,
        "confusion_matrix": confusion_matrix(gold, pred, labels=ALL_DECISIONS).tolist(),
        "gold_hold_predicted_hold": float((pred[~lab] == "HOLD").mean()) if (~lab).any() else None,
        "per_company": {
            comp: {"n": int((c == comp).sum()),
                   "macro_f1_strict": float(f1_score(g[c == comp], p[c == comp], labels=LABELS, average="macro", zero_division=0)),
                   "hold_rate": float((p[c == comp] == "HOLD").mean())}
            for comp in sorted(set(c))},
    })
    return res


def group_cv_select(gold, proba_by_variant, companies, taus=(0.0, 0.4, 0.5, 0.6, 0.7, 0.8), n_splits=None):
    """회사 단위 GroupKFold로 (입력 방식, tau)를 고른다.
    각 fold에서 학습 회사들로 고르고, 시험 회사로 잰다 → 선택 편향 없는 dev 추정치."""
    from sklearn.model_selection import GroupKFold
    from sklearn.metrics import f1_score
    gold, companies = np.asarray(gold), np.asarray(companies)
    n_splits = n_splits or len(set(companies))
    combos = [(v, t) for v in proba_by_variant for t in taus]

    def score(idx, v, t):
        m = np.isin(gold[idx], LABELS)
        return f1_score(gold[idx][m], decide(proba_by_variant[v][idx], t)[m], labels=LABELS, average="macro", zero_division=0)

    folds = []
    pred_oof = np.empty(len(gold), dtype=object)
    for tr, te in GroupKFold(n_splits=n_splits).split(gold, gold, companies):
        best = max(combos, key=lambda vt: score(tr, *vt))
        pred_oof[te] = decide(proba_by_variant[best[0]][te], best[1])
        folds.append({"test_companies": sorted(set(companies[te])), "chosen": best,
                      "test_macro_f1_strict": float(score(te, *best))})
    final_choice = max(combos, key=lambda vt: score(np.arange(len(gold)), *vt))
    return {"folds": folds, "oof_metrics": evaluate(gold, pred_oof, companies),
            "final_choice": {"variant": final_choice[0], "tau": final_choice[1]}}, pred_oof


def error_table(df, gold_col, pred_col):
    """오류를 사건 유형·연결 상태·회사별로 센다(오류 분석용)."""
    err = df.loc[df[gold_col].isin(LABELS) & (df[gold_col] != df[pred_col])].copy()
    err["error_type"] = err[gold_col] + "→" + err[pred_col]
    return err, err.groupby(["error_type", "link_status"]).size().rename("n").reset_index()


# ---------------------------------------------------------------------------
# 7. 잠금 점검 세트: 고정 → 잠금 → 한 번 평가
# ---------------------------------------------------------------------------
def freeze_config(config, path):
    """dev에서 고른 처리 방식을 파일로 고정한다. 이미 있으면 바꾸지 않는다."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"이미 고정된 설정이 있습니다: {path}")
    body = json.dumps(config, ensure_ascii=False, sort_keys=True)
    config = {**config, "config_sha256": hashlib.sha256(body.encode()).hexdigest()}
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def lock_holdout(holdout_targets, final_labels, path, manifest_path):
    """합의된 holdout 라벨을 잠근다. 잠금 후에는 해시로 변경 여부를 확인한다."""
    path, manifest_path = Path(path), Path(manifest_path)
    if path.exists() or manifest_path.exists():
        raise FileExistsError("이미 잠긴 holdout이 있습니다. 덮어쓰지 않습니다.")
    df = holdout_targets.merge(final_labels[["row_id", "final_decision"]], on="row_id", how="left")
    if df["final_decision"].isna().any():
        raise ValueError("최종 판정이 없는 holdout 행이 있습니다.")
    df["review_status"] = "LOCKED"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    cols = ["row_id", "text_original", "target_name", "final_decision"]
    manifest = {"rows": int(len(df)), "sha256": sha256_of(df, cols), "hash_columns": cols,
                "companies": sorted(df["company_name"].unique())}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def final_eval_once(holdout_path, manifest_path, config_path, result_path):
    """잠금·설정 고정을 확인한 뒤 holdout을 단 한 번 평가한다. 결과 파일이 있으면 다시 돌리지 않는다."""
    result_path = Path(result_path)
    if result_path.exists():
        raise FileExistsError("최종 평가는 이미 실행되었습니다. 재실행·재튜닝 금지.")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    df = pd.read_csv(holdout_path, encoding="utf-8-sig", dtype=str).fillna("")
    if sha256_of(df, manifest["hash_columns"]) != manifest["sha256"]:
        raise ValueError("holdout 내용이 잠금 이후 바뀌었습니다. 평가를 중단합니다.")
    proba = predict_proba([build_input(r, config["variant"]) for _, r in df.iterrows()], config["model_name"])
    pred = decide(proba, config["tau"])
    res = evaluate(df["final_decision"], pred, df["company_name"])
    res.update({"config": config, "holdout_sha256": manifest["sha256"]})
    result_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    df.assign(pred=pred, p_neg=proba[:, 0], p_neu=proba[:, 1], p_pos=proba[:, 2]).to_csv(
        result_path.with_suffix(".predictions.csv"), index=False, encoding="utf-8-sig")
    return res


# ---------------------------------------------------------------------------
# 8. 팀 데이터 계약 형식으로 내보내기 (schema/governance_agent_output.schema.json)
# ---------------------------------------------------------------------------
def _ymd(text):
    """'20260814' → '2026-08-14'. 형식이 다르면 None."""
    text = str(text or "")
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if re.fullmatch(r"\d{8}", text[:8] or "") else None


def to_contract_sentiment(rows, proba, roster, method):
    """대상 행(rows)과 모델 확률(proba, LABELS 순서)을 계약 형식의 S 주장·근거·미확인 목록으로 바꾼다.

    - 감성은 검증 전이므로 모든 주장은 label=HOLD, reportStatus=hold, validationStatus=UNVALIDATED다.
      확률은 참고값으로만 싣는다. 규칙 판정(signal)은 만들지 않는다.
    - 근거는 기사(N+기사번호)와 DART 명부(R+인물번호) 두 종류다. 같은 근거는 한 번만 넣는다.
    - 공개시각을 모르는 기사는 unresolved에 DATE_UNKNOWN으로 올린다(미래정보 검사 불가 표시).
    """
    people = roster.set_index("person_id")
    claims, evidence, unresolved = [], {}, []
    for i, (_, r) in enumerate(rows.reset_index(drop=True).iterrows()):
        cid = f"S{i + 1:02d}"
        nid = r["news_id"]
        if nid not in evidence:
            pub = r["event_date"] or None
            evidence[nid] = {
                "evidenceId": nid, "sourceType": "NEWS" if r["source_type"] == "news_title" else "COMPANY_RELEASE",
                "verificationStatus": "보도", "sourceTag": "[보도]", "item": "기사 제목",
                "quote": r["text_original"], "value": None, "dataDate": None,
                "publishedAt": pub, "publishedAtSource": "URL" if pub else "UNKNOWN", "url": r["source_url"],
            }
            if not pub:
                unresolved.append({"evidenceId": nid, "item": f"{nid} 기사 게시일", "reason": "DATE_UNKNOWN",
                                   "affectsClaimIds": []})
        claim_ev = [nid]
        target = {"personId": r["target_id"], "name": r["target_name"], "role": r["target_role"]}
        if r["target_id"]:
            p = people.loc[r["target_id"]]
            rid = "R" + r["target_id"][1:]
            target["rosterEvidenceId"] = rid
            claim_ev.append(rid)
            if rid not in evidence:
                ratio = pd.to_numeric(p["stake_ratio_end"], errors="coerce")
                evidence[rid] = {
                    "evidenceId": rid, "sourceType": "DART_DISCLOSURE", "verificationStatus": "공시",
                    "sourceTag": f"[공시 {p['rcept_no']}]", "item": f"{p['canonical_name']}: {p['role']}",
                    "value": None if pd.isna(ratio) else float(ratio), "unit": "%" if not pd.isna(ratio) else "",
                    "dataDate": p["as_of"], "publishedAt": _ymd(p["rcept_no"]), "publishedAtSource": "RCEPT_NO",
                    "rceptNo": p["rcept_no"], "url": p["source_url"],
                }
        for u in unresolved:
            if u["evidenceId"] == nid:
                u["affectsClaimIds"].append(cid)
        claims.append({
            "claimId": cid, "claimType": "interpretation", "kind": "person_event_sentiment",
            "area": "B" if "CEO" in r["target_role"] else "A",
            # 문장에는 숫자를 넣지 않는다(검사기의 숫자 생성 금지 규칙). 기사 번호는 evidenceIds로 가리킨다
            "statement": f"기사 속 {target['name']} 관련 사건의 주주 영향은 판정을 보류한다.",
            "evidenceIds": claim_ev,
            "sentiment": {"target": target, "label": "HOLD",
                          "probabilities": {lab: round(float(proba[i, k]), 4) for k, lab in enumerate(LABELS)},
                          "method": method, "validationStatus": "UNVALIDATED"},
            "reportStatus": "hold", "holdReason": "감성 모델 검증 전(잠금 점검 세트 평가 전)",
        })
    if claims:
        unresolved.append({"item": "대주주·CEO 대상 감성 모델(잠금 점검 세트 평가 전)", "reason": "UNVALIDATED_MODEL",
                           "affectsClaimIds": [c["claimId"] for c in claims]})
    return claims, list(evidence.values()), unresolved
