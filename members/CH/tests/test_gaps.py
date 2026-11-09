"""#62 미확보·미확인 목록 정리: 중복 합침 · 묶음 · 내부 코드 한국어화 · 처리 통계 분리. 실제 시연 화면에서 나온 항목을 그대로 쓴다."""
from ch_agents import contract, gaps

SCREEN = [      # 사용자 보고(11/5) 시연 화면의 미확보 목록 (질의응답 답)
    {"label": "호가 잔량", "reason": "LLM 이 근거 부족으로 보고"},
    {"label": "세부 주체(금융투자·투신·연기금)", "reason": "LLM 이 근거 부족으로 보고"},
    {"label": "2026-11-04 투자자별 수급(수집이 시세보다 늦음)", "reason": "LLM 이 근거 부족으로 보고"},
    {"label": "블로그 감성 변화(직전 기간 문서 2674건·5일뿐)", "reason": "LLM 이 근거 부족으로 보고"},
    {"label": "거시지표 발표·수정 이력(Point-in-Time) 미보관", "reason": "LLM 이 근거 부족으로 보고"},
    {"label": "호가 잔량", "reason": "범위 밖 — 공개·무로그인 출처 없음(외국인·기관 합계로 대체)"},
    {"label": "세부 주체(금융투자·투신·연기금)", "reason": "범위 밖 — 공개·무로그인 출처 없음(외국인·기관 합계로 대체)"},
    {"label": "2026-11-04 투자자별 수급 (수집이 시세보다 늦음, 마지막 2026-11-03)", "reason": "N08 미충족 항목"},
    {"label": "블로그 감성 변화", "reason": "직전 기간 문서 2674건·5일뿐 (수집 기간 짧음)"},
    {"label": "근거 문장을 붙이지 못해 점수를 내지 않은 문서 0건, 대상 기업 아님으로 분리한 문서 9건", "reason": "N11 미충족 항목"},
    {"label": "거시지표 발표·수정 이력(Point-in-Time) 미보관: 최신값 위주이며 공표일은 보수 규칙으로 추정 (D1 사후 탐색 등급)", "reason": "N05 미충족 항목"},
    {"label": "감성 판정 한계", "reason": "키워드 사전 기준선 — 사람 라벨 600건 중 감성 대상 440건 기준 정확도 56.6%"},
]


def test_screen_list_merges_duplicates_and_groups_by_kind():
    items, proc = gaps.organize(SCREEN)
    labels = {(i["groupLabel"], i["label"]) for i in items}
    assert len(items) == 5 and gaps.gap_problems(items) == []
    assert ("범위 밖", "호가 잔량, 세부 투자 주체(금융투자·투신·연기금)") in labels            # #75: 범위 밖 두 줄 → 한 줄
    assert ("기준일 차이", "수급은 11/3 기준") in labels and ("수집 중", "블로그 감성 변화") in labels
    assert ("미확보", "거시지표 발표·수정 이력") in labels and ("한계", "감성 판정 정확도") in labels
    assert proc == ["대상 기업 아님으로 분리한 문서 9건"]                       # 0건 조각은 버리고 처리 통계는 처리 기록으로
    hoga = next(i for i in items if i["label"].startswith("호가 잔량"))
    assert hoga["sources"] == ["노드 점검", "에이전트 판단"]                      # 같은 항목은 한 줄, 출처는 표시로만
    order = [i["groupLabel"] for i in items]
    assert order == sorted(order, key=list(gaps.GROUPS.values()).index)          # 묶음 순서


def test_internal_codes_are_korean_everywhere():
    items, _ = gaps.organize(SCREEN)
    text = " ".join(f"{i['label']} {i['detail']} {i['reason']}" for i in items)
    assert not gaps.RAW_CODE_RE.search(text) and "Point-in-Time" not in text
    assert gaps.ko_text("N08 미충족 항목, D1 사후 탐색 등급") == "수급 해석 미충족 항목, 사후 탐색 단계(검증 전)"
    assert gaps.ko_text("거시지표 발표·수정 이력(Point-in-Time) 미보관") == "거시지표 발표·수정 이력 미보관"


def test_gap_problems_flags_duplicates_codes_zero_counts_and_limits_in_missing():
    bad = gaps.gap_problems([{"group": "missing", "label": "A"}, {"group": "missing", "label": "A"}, {"group": "missing", "label": "N08 점검"},
                             {"group": "missing", "label": "문서 0건"}, {"group": "missing", "label": "감성 판정 한계"}])
    assert len(bad) >= 4 and any("중복" in b for b in bad) and any("내부 코드" in b for b in bad) and any("0건" in b for b in bad) and any("한계" in b for b in bad)


def test_contract_unverified_is_tidied_but_schema_still_valid():
    u = gaps.tidy([{"item": "호가 잔량", "reason": "범위 밖 — 공개·무로그인 출처 없음", "category": "무자료", "status": "미확인", "evidenceIds": ["E1"]},
                   {"item": "호가 잔량", "reason": "에이전트가 판단에 필요하다고 본 미확인 항목", "category": "판단 보류", "status": "미확인", "evidenceIds": ["E2"]},
                   {"item": "수급 해석 N08 미충족", "reason": "N08 미충족 항목", "category": "무자료", "status": "미확인", "evidenceIds": []}])
    assert len(u) == 2 and u[0]["evidenceIds"] == ["E1", "E2"] and u[0]["group"] == "out_of_scope" and u[0]["sources"] == ["노드 점검", "에이전트 판단"]
    assert "N08" not in u[1]["item"] and u[1]["groupLabel"] == "미확보"
    assert contract.SCHEMA_VERSION  # 필드 추가는 선택 필드라 옛 결과도 검증 통과 (test_brief·test_outlook 에서 확인)

def test_trailing_word_byeonsu_does_not_make_a_second_topic():
    items, _ = gaps.organize([{"label": "관세·통상정책 변수(DB 미보관)", "reason": ""}, {"label": "관세·통상정책", "reason": ""}])
    assert len(items) == 1


def test_ledger_key_lists_are_removed_from_label_and_reason():
    items, _ = gaps.organize([{"label": "블로그·카페 최근 7일 수치", "reason": "T1056·T1057·T1058·T1059"}])
    assert items and "T10" not in str(items) and gaps.gap_problems(items) == []
    assert gaps.RAW_CODE_RE.search("사유 T1056") and not gaps.RAW_CODE_RE.search("3분기 Q3 H1 실적")


def test_processing_stats_are_split_canonicalized_and_deduped():
    _, proc = gaps.organize([
        {"label": "근거 문장 미부착으로 점수 미산출 문서 1건 및 대상 기업 아님으로 분리한 문서 9건(심리·뉴스 데이터 점검 미충족)", "reason": ""},
        {"label": "근거 문장을 붙이지 못해 점수를 내지 않은 문서 1건, 대상 기업 아님으로 분리한 문서 9건", "reason": ""},
        {"label": "대상 기업 아님으로 분리한 문서 9건(심리·뉴스 데이터 점검 미충족 항목)", "reason": ""}])
    assert proc == ["근거 문장을 붙이지 못해 점수를 내지 않은 문서 1건", "대상 기업 아님으로 분리한 문서 9건"]


# ---- #75: 시연에서 드러난 미확보·한계 표시 오류
def _one(items, group):
    return [i for i in items if i["group"] == group]


def test_parenthesis_and_comma_stay_in_the_item_name():
    items, _ = gaps.organize([{"label": "금리 경로별(소비 위축, 차입 비용, 할인율)", "reason": "LLM 이 근거 부족으로 보고"},
                              {"label": "외환 파생상품(통화선도 등)", "reason": "N05 미충족 항목"},
                              {"label": "수출 매출 비중(FY2025)", "reason": "미충족 항목"}])
    assert [i["label"] for i in items] == ["금리 경로별(소비 위축, 차입 비용, 할인율)", "외환 파생상품(통화선도 등)", "수출 매출 비중(FY2025)"]


def test_trailing_mark_does_not_make_a_duplicate():
    items, _ = gaps.organize([{"label": "기업 IT 투자 경기", "reason": "DB에 없음"}, {"label": "기업 IT 투자 경기 ※", "reason": "이 업종 경로에 필요하지만 DB에 없는 변수"}])
    assert len(items) == 1 and "※" not in items[0]["label"]


def test_too_few_scored_documents_is_collecting_not_missing():
    items, _ = gaps.organize([{"label": "유튜브 댓글 감성", "reason": "점수 붙은 문서 4건 (최소 5건)"}])
    assert items[0]["groupLabel"] == "수집 중" and "표본 부족" in items[0]["detail"]


def test_llm_internal_meta_gaps_are_dropped_or_merged_into_the_accuracy_limit():
    items, _ = gaps.organize([{"label": "감성 모델 개선 후 정확도 및 긍정 탐지 변화", "reason": "한계"},
                              {"label": "감성 판정 한계", "reason": "키워드 사전 기준선 — 정확도 56.6%"},
                              {"label": "블로그·카페 문서 중 종목 태그가 매핑되지 않은 글의 정확한 비중", "reason": "미확보"},
                              {"label": "장중·장후 구분 불가로 사건 당일 반응과 후속 반응의 세부 시점 구분", "reason": "미확보"}])
    assert [(i["groupLabel"], i["label"]) for i in items] == [("한계", "감성 판정 정확도")]


def test_scope_items_fold_into_one_line_but_unrelated_scope_items_stay():
    items, _ = gaps.organize([{"label": "호가 잔량", "reason": "범위 밖 — 공개·무로그인 출처 없음"}, {"label": "세부 투자 주체(금융투자·투신·연기금)", "reason": "범위 밖 — 공개·무로그인 출처 없음"},
                              {"label": "분석 대상 밖 종목: 에코프로비엠", "reason": "국내 KOSPI 200 등만 분석"}])
    labels = [i["label"] for i in _one(items, "out_of_scope")]
    assert labels == ["호가 잔량, 세부 투자 주체(금융투자·투신·연기금)", "분석 대상 밖 종목: 에코프로비엠"]
    assert "'" not in labels[1]


FIN_GAPS = [{"label": "최근 4개 분기 영업이익 대비 환율 민감도", "reason": "미확보"}, {"label": "환율 민감도", "reason": "사업보고서 원문에서 민감도 표를 찾지 못함"},
            {"label": "수출 매출 비중", "reason": "사업보고서 원문에서 회사 전체 내수·수출 표를 찾지 못함"}, {"label": "단독분기 매출 이력 및 다음 분기 매출 기준선 예측", "reason": "미확보"},
            {"label": "최근 4개 분기", "reason": "기준일에 공시된 연속 4개 분기 영업이익 없음"}, {"label": "다음 분기 매출 기준선 예측", "reason": "기준일에 공시된 분기 매출 없음"},
            {"label": "관세·통상정책", "reason": "DB에 없는 변수"}]


def test_financial_company_not_applicable_items_are_one_group():
    items, _ = gaps.organize(FIN_GAPS, financial=True)
    na = _one(items, "not_applicable")
    assert len(na) == 1 and na[0]["groupLabel"] == "해당 없음" and "금융업 계정 구조" in na[0]["detail"]
    assert na[0]["label"] == "단독분기 매출 이력, 다음 분기 매출 기준선, 최근 4개 분기 영업이익, 수출 매출 비중, 환율 민감도"
    assert [i["label"] for i in _one(items, "missing")] == ["관세·통상정책"]
    plain, _ = gaps.organize(FIN_GAPS)                       # 금융업이 아니면 그대로 미확보
    assert not _one(plain, "not_applicable") and len(_one(plain, "missing")) == 5      # #79: 더 긴 이름에 핵심 명사가 모두 든 "최근 4개 분기"·"다음 분기 매출 기준선 예측" 은 그 항목에 합쳐짐


def test_financial_company_is_decided_by_industry_code_not_holding_company_code_alone():
    assert gaps.is_financial_company("64121", "카카오뱅크") and gaps.is_financial_company("65121", "삼성화재") and gaps.is_financial_company("66121", "삼성증권")
    assert gaps.is_financial_company("64992", "KB금융") and gaps.is_financial_company("64992", "신한지주")
    assert not gaps.is_financial_company("64992", "SK") and not gaps.is_financial_company("64992", "LG") and not gaps.is_financial_company("264", "삼성전자")
    assert not gaps.is_financial_company(None, "KB금융")


def test_similar_missing_items_with_contained_key_nouns_merge_into_one_line():     # #79
    items, _ = gaps.organize([{"label": "수출 매출 비중(회사 공시)", "reason": "LLM 이 근거 부족으로 보고"},
                              {"label": "회사 전체 내수·수출 매출 비중", "reason": "공시에 구분 없음"}])
    assert len(items) == 1 and items[0]["label"] == "회사 전체 내수·수출 매출 비중"
    assert gaps.key_nouns("수출 매출 비중(회사 공시)") == {"수출", "매출", "비중"}


def test_items_with_few_shared_nouns_or_different_groups_do_not_merge():
    items, _ = gaps.organize([{"label": "단독분기 매출 이력", "reason": "x"}, {"label": "매출 비중", "reason": "y"},
                              {"label": "환율 민감도 수치", "reason": "z"}])
    assert len(items) == 3
