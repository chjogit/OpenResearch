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
    assert len(items) == 6 and gaps.gap_problems(items) == []
    assert ("범위 밖", "호가 잔량") in labels and ("범위 밖", "세부 투자 주체(금융투자·투신·연기금)") in labels
    assert ("기준일 차이", "수급은 11/3 기준") in labels and ("수집 중", "블로그 감성 변화") in labels
    assert ("미확보", "거시지표 발표·수정 이력") in labels and ("한계", "감성 판정 정확도") in labels
    assert proc == ["대상 기업 아님으로 분리한 문서 9건"]                       # 0건 조각은 버리고 처리 통계는 처리 기록으로
    hoga = next(i for i in items if i["label"] == "호가 잔량")
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
