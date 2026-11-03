"""#26 방향 점검 절 단위: 10-30·#25 v2 성적표에서 지워진 맞는 문장은 통과, 같은 절의 진짜 위반은 그대로 잡힘."""
from ch_agents.facts import Facts
from ch_agents.semantic import direction_problems


def _f():
    f = Facts("S")
    f.add("기관 직전 20일 순매수 수량", -8312196, "주", "2026-10-30", "t", kind="calc")    # S1 (순매도)
    f.add("기관 최근 5일 순매수 수량", 4648745, "주", "2026-10-30", "t", kind="calc")      # S2
    f.add("기관 20일 순매수 수량", -598864, "주", "2026-10-30", "t", kind="calc")          # S3
    f.add("기관 20일 순매수 금액(근사)", -9000000000, "KRW±", "2026-10-30", "t", kind="calc")  # S4
    f.add("주가 20일 등락률", -20.16, "%chg", "2026-10-30", "t", kind="calc")              # S5
    f.add("기관 20일 순매수 수량(+)", 384100, "주", "2026-10-30", "t", kind="calc")        # S6
    f.add("상관 250일", 0.45, "coef", "-", "t", kind="calc")                              # S7
    f.add("상관 60일", 0.1, "coef", "-", "t", kind="calc")                                # S8
    f.flag("250일 상관 강함·유의함 ({S7}), 60일 상관 약함·유의하지 않음 ({S8})")
    return f


FALSE_POSITIVES = [   # 실제로 지워졌던 문장 (맞는 서술)
    "기관 순매매 방향은 직전 20일 순매도 {S1}에서 최근 5일 순매수 {S2}로 바뀌었다.",
    "기관 최근 5일 순매수 수량 {S2}이 직전 20일 순매도 {S1}와 방향이 다릅니다.",
    "기관 20일 순매수 수량 {S3}과 기관 20일 순매수 금액(근사) {S4}은 순매도입니다.",
    "20일 주가 하락 {S5}과 기관 순매수 {S6}이 동시에 나타난 점",
    "기관 순매수 수량은 {S3}이고 20일 순매수 금액은 {S4}이며 모두 순매도다.",
    "250일 상관 {S7}은 유의하지 않으며, 60일 상관 {S8}은 유의합니다.",
]


def test_real_false_positives_now_pass():
    f = _f()
    for t in FALSE_POSITIVES[:-1]:
        assert direction_problems(t, f) == [], t


def test_clause_boundary_for_direction_words():
    f = _f()
    # 250일 상관은 유의, 60일 상관은 유의하지 않음 — 서로 다른 절의 표현이라 섞이지 않음
    assert direction_problems("250일 상관 {S7}은 유의하며, 60일 상관 {S8}은 유의하지 않습니다.", f) == []


def test_real_violations_in_same_clause_still_caught():
    f = _f()
    assert direction_problems("기관은 20일간 {S3} 순매수했다.", f)                       # 값 - 인데 순매수
    assert direction_problems("주가는 20일 {S5} 올랐다.", f)                              # 값 - 인데 상승
    assert direction_problems("기관은 최근 5일 {S2} 순매도했다.", f)                       # 값 + 인데 순매도
    assert direction_problems("기관은 {S3}을 기록하며 순매수 우위였고 20일 {S4}도 순매수다.", f)  # S3 뒤 같은 절 순매수
    assert direction_problems("250일 상관 {S7}은 유의하지 않다.", f)                       # 유의 판정을 뒤집음
    assert direction_problems("60일 상관 {S8}은 유의한 관계다.", f)                         # 비유의를 유의로
    assert direction_problems("250일 상관 {S7}은 유의하지 않으며 60일 상관 {S8}은 유의하지 않다.", f)   # 첫 절이 판정과 반대


def _refs_facts():
    f = Facts("S")
    f.add("외국인 20일 순매수 수량", -16281016, "주", "2026-10-30", "t", kind="calc")        # S1
    f.add("외국인+기관 20일 순매수 수량", -17784662, "주", "2026-10-30", "t", kind="calc")  # S2
    f.add("외국인 60일 순매수 수량", 120000, "주", "2026-10-30", "t", kind="calc")          # S3
    return f


def test_label_words_and_other_windows_are_not_claims_for_refs():
    f = _refs_facts()
    ok = [   # 근거 키만 단 문장 — 실제로 지워졌던 맞는 서술
        ("외국인 20일 순매수 수량은 순매도이며 연속 순매도 일수는 길다.", ["S1"]),
        ("개인 20일 순매수 수량은 순매수이며 외국인+기관 20일 순매수 수량과 방향이 반대입니다.", ["S2"]),
        ("외국인 60일 순매수 수량이 크게 쌓여 중장기 누적은 순매수여서 최근 20일 순매도와 방향이 다릅니다.", ["S1", "S3"]),
    ]
    for t, refs in ok:
        assert direction_problems(t, f, refs) == [], t


def test_real_ref_sign_violations_still_caught():
    f = _refs_facts()
    assert direction_problems("외국인 20일 순매수 수량은 순매수를 기록했다.", f, ["S1"])
    assert direction_problems("외국인+기관은 20일간 순매수로 돌아섰다.", f, ["S2"])


def test_negated_causation_wording_is_not_misnaming():
    f = Facts("S")
    f.add("주가-원/달러 상관(250일)", 0.2, "coef", "-", "t", kind="calc")   # S1
    assert direction_problems("250일 상관 {S1}은 통계적 동조성일 뿐 노출·인과가 아닙니다.", f) == []
    assert direction_problems("250일 상관 {S1}은 환율 때문에 생긴 것이다.", f)
