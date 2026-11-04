"""#39 감성 평가셋: 표본 추출 배분, 라벨러별 시트(사전 점수 비노출), 다수결·SW 확인 목록, Fleiss/Cohen kappa, 사전 성능 (DB 없이)."""
import csv
import random

import pytest

from ch_agents import sentiment_eval as se

openpyxl = pytest.importorskip("openpyxl")


def _rows(n=40):
    srcs = list(se.SOURCE_KO)
    labs = list(se.DICT_CELLS)
    return [{"doc_id": 1000 + i, "company_id": i % 5, "source": srcs[i % 5], "ticker": f"00{i % 5}", "name": f"기업{i % 5}",
             "published_at": f"2026-10-{20 + i % 9}", "title": f"제목 {i}", "summary": f"요약 {i} " * 4, "url": f"https://x/{i}",
             "dict_label": labs[i % 4], "dict_score": 0.1 * (i % 4)} for i in range(n)]


def test_split_quota_sums_and_is_even():
    q = se.split_quota(150)
    assert sum(q.values()) == 150 and max(q.values()) - min(q.values()) <= 1
    assert sum(se.QUOTAS.values()) == 600


def test_pick_rows_balances_cells_dedupes_titles_and_fills_shortfall():
    pool = {"positive": [{"doc_id": i, "title": f"p{i}"} for i in range(30)],
            "neutral": [{"doc_id": 100 + i, "title": f"n{i}"} for i in range(2)],            # 부족한 칸
            "negative": [{"doc_id": 200 + i, "title": "같은 제목"} for i in range(30)],        # 제목 중복
            "none": [{"doc_id": 300 + i, "title": f"x{i}"} for i in range(30)]}
    got = se.pick_rows(lambda lab, n: pool[lab][:n], 20, "s")
    assert len(got) == 20 and len({r["title"] for r in got}) == 20
    assert sum(r["doc_id"] < 100 for r in got) >= 5 and sum(100 <= r["doc_id"] < 200 for r in got) == 2


def test_dedupe_keeps_different_comments_under_same_video_title():
    pool = {lab: [{"doc_id": i, "title": "영상 제목", "summary": f"댓글 {lab}{i}"} for i in range(30)] for lab in se.DICT_CELLS}
    got = se.pick_rows(lambda lab, n: pool[lab][:n], 20, "s")
    assert len(got) == 20
    dup = {lab: [{"doc_id": i, "title": "같은 기사", "summary": "같은 요약"} for i in range(30)] for lab in se.DICT_CELLS}
    assert len(se.pick_rows(lambda lab, n: dup[lab][:n], 20, "s")) == 1


def test_sheets_same_docs_different_order_and_no_dict_scores(tmp_path):
    rows = _rows()
    meta = se.build_sheets(rows, tmp_path, "2026-11-03")
    assert meta["n"] == 40 and meta["by_source"]["naver_news"] == 8
    orders = {}
    for lab in se.LABELERS:
        ws = openpyxl.load_workbook(tmp_path / f"labeler_{lab}.xlsx").active
        head = [c.value for c in ws[1]]
        assert head == se.SHEET_COLS and not {"사전", "dict_label", "dict_score"} & set(head)
        orders[lab] = [r[0] for r in ws.iter_rows(min_row=2, values_only=True)]
        assert ws.data_validations.dataValidation                      # 드롭다운
    assert sorted(orders["A"]) == sorted(orders["B"]) == sorted(orders["C"]) and orders["A"] != orders["B"]
    full = list(csv.DictReader(open(tmp_path / "sample_full.csv", encoding="utf-8-sig")))
    assert len(full) == 40 and full[0]["title"] and "dict_label" in full[0]          # 원문 보존 + 채점용 사전 라벨
    assert se.build_sheets(rows, tmp_path / "again", "2026-11-03") and \
        [r[0] for r in openpyxl.load_workbook(tmp_path / "again" / "labeler_A.xlsx").active.iter_rows(min_row=2, values_only=True)] == orders["A"]


def test_fleiss_known_values():
    assert se.fleiss_kappa([["긍정"] * 3, ["부정"] * 3, ["중립"] * 3]) == pytest.approx(1.0)
    assert se.fleiss_kappa([["긍정"] * 3] * 4) is None                      # 변동이 없으면 정의되지 않음
    # 두 라벨러가 거의 같은 값을 쓰는 경우는 Cohen 과 같은 방향
    a = ["긍정", "부정", "중립", "긍정", "부정", "중립"]
    assert se.fleiss_kappa([[x, x] for x in a]) == pytest.approx(1.0)
    k = se.fleiss_kappa([["긍정", "긍정", "부정"], ["부정", "부정", "중립"], ["중립", "긍정", "중립"], ["긍정", "긍정", "긍정"]])
    assert -1 < k < 1


def test_decide_majority_and_sw_cases():
    assert se.decide(["긍정", "긍정", "부정"]) == {"majority": "긍정", "needs_sw": False}
    assert se.decide(["긍정", "중립", "부정"]) == {"majority": None, "needs_sw": True}
    d = se.decide(["긍정", "긍정", "무관"])                                   # 무관이 갈림 → 다수결은 있으나 SW 확인
    assert d["majority"] == "긍정" and d["needs_sw"]
    assert se.decide(["무관", "무관", "무관"])["needs_sw"] is False


def _fill(path, labels, unc=None, fmt="xlsx"):
    """시트의 감성 열을 채워 같은 이름으로 저장 (id 순서대로 labels dict 사용)."""
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    for r in ws.iter_rows(min_row=2):
        i = int(r[0].value)
        r[7].value = labels[i]
        r[8].value = (unc or {}).get(i, "아니오")
    wb.save(path)


def test_score3_end_to_end(tmp_path):
    rows = _rows(12)
    se.build_sheets(rows, tmp_path, "2026-11-03")
    (tmp_path / "returned").mkdir()
    ids = [r["doc_id"] for r in rows]
    # 정답이 되어야 하는 값: 사전과 일부러 어긋나게
    truth = {i: se.SHEET_LABELS[k % 3] for k, i in enumerate(ids)}                  # 긍정/중립/부정 반복
    a, b, c = dict(truth), dict(truth), dict(truth)
    b[ids[0]] = "부정"                                                              # 2:1 → 다수결 정답 유지
    a[ids[1]], b[ids[1]], c[ids[1]] = "긍정", "중립", "부정"                         # 셋 다 다름 → SW
    c[ids[2]] = "무관"                                                              # 무관 갈림 → SW
    for lab, lab_map in zip(se.LABELERS, (a, b, c)):
        import shutil
        shutil.copy(tmp_path / f"labeler_{lab}.xlsx", tmp_path / "returned" / f"labeler_{lab}.xlsx")
        _fill(tmp_path / "returned" / f"labeler_{lab}.xlsx", lab_map)
    out = se.score3(tmp_path, tmp_path)
    assert out["n_complete_3"] == 12 and out["n_gold"] == 10 and out["n_sw_pending"] == 2
    sw = list(csv.DictReader(open(tmp_path / "sw_check_list.csv", encoding="utf-8-sig")))
    assert {int(r["id"]) for r in sw} == {ids[1], ids[2]} and sw[0]["A"] in se.SHEET_LABELS
    assert 0 < out["kappa_sentiment_fleiss"] < 1 and out["kappa_sentiment_pairs"]["AC"] < 1
    # SW 확인 결과를 넣으면 정답이 늘고 대기가 0
    with open(tmp_path / "sw_resolved.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "감성"])
        w.writerow([ids[1], "중립"])
        w.writerow([ids[2], "무관"])
    out2 = se.score3(tmp_path, tmp_path)
    assert out2["n_gold"] == 12 and out2["n_sw_pending"] == 0 and out2["irrelevant_share"] == pytest.approx(100 / 12)
    assert out2["n_eval"] == 11 and 0 <= out2["accuracy"] <= 100 and set(out2["per_class"]) == {"긍정", "중립", "부정"}
    assert "naver_news" in out2["by_source"] or out2["by_source"]


def test_read_sheet_accepts_english_and_csv(tmp_path):
    p = tmp_path / "x.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(se.SHEET_COLS)
        w.writerow([7, "a", "뉴스", "d", "t", "s", "u", "positive", "예", ""])
        w.writerow([8, "a", "뉴스", "d", "t", "s", "u", "엉뚱", "", ""])
    got = se.read_sheet(p)
    assert got["7"]["감성"] == "긍정" and got["7"]["불확실성"] == "예" and got["8"]["감성"] == ""


def test_find_returned_picks_latest_version(tmp_path):
    r = tmp_path / "returned"
    r.mkdir()
    for n in ("labeler_A_labeled_v2.xlsx", "labeler_A_labeled_v3.xlsx", "labeler_A_labeled_v10.xlsx", "labeler_B.xlsx", "memo.txt"):
        (r / n).write_text("x")
    assert se._find_returned(tmp_path, "A").name == "labeler_A_labeled_v10.xlsx"      # 문자열 정렬이 아니라 숫자 버전
    assert se._find_returned(tmp_path, "B").name == "labeler_B.xlsx" and se._find_returned(tmp_path, "C") is None
