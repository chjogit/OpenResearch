"""의미 점검: LLM 문장이 숫자 장부·코드 판정과 '방향'이 반대인지 코드로 확인합니다.

형식 검사(키 밖 숫자, 금지 표현)는 숫자가 장부 값인지만 봅니다. 그래서 값은 맞게 인용하고
뜻을 반대로 쓴 문장(예: 코스피 대비 +0.71%p 를 '초과 손실'로 해석)은 통과합니다. 여기서는 두 가지를 봅니다.

1. 판정 방향: 코드 판정에 쓰인 방향어(상회/하회, 가속/둔화, 개선/악화, 인상/인하, 원화 강세/약세,
   상관 강함/보통/약함, 유의함/유의하지 않음)를 판정 속 키에 연결해 두고, 그 키를 인용한 문장이 반대 방향어만 쓰면 불일치로 봅니다.
2. 부호 방향: 증감을 나타내는 값(%, %p, 주, 원±, 점수)의 키 바로 뒤에 반대 부호의 서술어
   (값이 +인데 '감소·하락·순매도', 값이 -인데 '증가·상승·순매수')가 오면 불일치로 봅니다.

두 점검 모두 맞는 방향어가 함께 있으면 문제 삼지 않습니다(오탐을 줄이기 위해 보수적으로 판단).
"""
from __future__ import annotations

import re

from .facts import Facts

KEY_RE = re.compile(r"\{([A-Z]\d+)\}")

# (방향 이름, 이 방향을 뜻하는 표현, 반대 방향을 뜻하는 표현)
DIRECTIONS = [
    ("상회", ("상회", "웃돌", "앞서", "초과 수익", "덜 하락", "덜 빠"), ("하회", "밑돌", "뒤처", "초과 손실", "부진")),
    ("하회", ("하회", "밑돌", "뒤처", "초과 손실", "부진"), ("상회", "웃돌", "앞서", "초과 수익", "덜 하락", "덜 빠")),
    ("가속", ("가속",), ("둔화",)),
    ("둔화", ("둔화",), ("가속",)),
    ("개선", ("개선",), ("악화",)),
    ("악화", ("악화",), ("개선",)),
    ("인상", ("인상",), ("인하",)),
    ("인하", ("인하",), ("인상",)),
    ("원화 강세", ("원화 강세", "원화가 강세", "달러 약세"), ("원화 약세", "원화가 약세", "달러 강세")),
    ("원화 약세", ("원화 약세", "원화가 약세", "달러 강세"), ("원화 강세", "원화가 강세", "달러 약세")),
    # 동조성: 크기(강함/보통/약함)와 유의성(유의함/유의하지 않음)을 따로 봅니다 (facts.corr_label)
    ("강함", ("강한", "강하", "강함", "뚜렷"), ("약한 동조", "약하게 동조", "동조가 약", "동조는 약", "약한 역방향",
                                             "상관 약", "상관이 약", "상관은 약")),
    ("보통", ("보통", "중간"), ("뚜렷", "강한 동조", "강하게 동조", "상관 강", "상관이 강")),
    ("약함", ("약한", "약하", "약함"), ("뚜렷", "강한 동조", "강하게 동조", "상관 강", "상관이 강", "상관 보통")),
    ("유의", ("유의함", "유의한", "유의하다", "유의미"), ("유의하지 않", "유의하지않", "무의미")),
    ("비유의", ("유의하지 않", "유의하지않", "무의미"), ("유의함", "유의한", "유의하다", "유의미")),
    ("시장 동행", ("같은 방향", "동행", "함께"), ("반대 방향", "역행", "시장과 달리", "시장과 다른")),
    ("시장 역행", ("반대 방향", "역행", "시장과 달리", "시장과 다른"), ("같은 방향", "동행")),
]
# 판정 문장에서 방향어를 찾을 때 쓰는 대표 표현 (판정은 코드가 만든 정해진 문형)
FLAG_MARKERS = {
    "상회": ("상회",), "하회": ("하회",), "가속": ("가속",), "둔화": ("둔화",), "개선": ("개선",),
    "악화": ("악화",), "인상": ("인상 국면",), "인하": ("인하 국면",), "원화 강세": ("원화 강세",),
    "원화 약세": ("원화 약세",),
    "강함": ("상관 강함",), "보통": ("상관 보통",), "약함": ("상관 약함",),
    "유의": ("·유의함",), "비유의": ("·유의하지 않음",),
    "시장 동행": ("시장과 같은 방향",), "시장 역행": ("시장과 반대 방향",),   # 에이전트 3 시장 기준선 판정
}

# 항목의 뜻과 다른 개념으로 부르는 표현 (항목 이름에 든 단어들 → 쓰면 안 되는 표현)
MISNAMED = [
    (("외국인", "평균 가격"), ("매입 단가", "매수 단가", "평균 단가", "평단")),   # 순매수일 종가 가중 평균일 뿐
    (("상관",), ("인과", "때문에", "덕분에")),                                    # 통계적 동조성
    (("대차잔고",), ("공매도 잔고", "공매도 물량")),                              # 공매도의 대용치일 뿐
]

SIGN_UNITS = {"%chg", "%p", "주", "KRW±", "score"}
POS_WORDS = ("증가", "상승", "늘어", "늘었", "개선", "확대", "순매수", "흑자", "플러스", "초과 수익", "올랐", "오름")
NEG_WORDS = ("감소", "하락", "줄어", "줄었", "악화", "축소", "순매도", "적자", "마이너스", "초과 손실", "내렸", "떨어")
WINDOW = 12  # 키 뒤 몇 글자까지 서술어로 볼지


def flag_directions(f: Facts) -> dict[str, set[str]]:
    """코드 판정 문장을 쉼표 단위로 나눠, 각 조각의 키에 그 조각의 방향어를 연결합니다."""
    out: dict[str, set[str]] = {}
    for fl in f.flags:
        for seg in re.split(r",\s*", fl):
            keys = KEY_RE.findall(seg)
            if not keys:
                continue
            text = KEY_RE.sub("", seg)
            found = set()
            for name, markers in FLAG_MARKERS.items():
                if any(mk in text for mk in markers):
                    found.add(name)
            sizes = found & {"강함", "보통", "약함"}
            if len(sizes) > 1:  # 한 조각에 크기가 둘 이상이면 판정이 모호하므로 크기는 점검하지 않음
                found -= sizes
            for k in keys:
                out.setdefault(k, set()).update(found)
    return out


def _after(text: str, end: int) -> str:
    rest = text[end:end + WINDOW]
    cut = re.search(r"[{,.;]|이나|지만|으며|이며", rest)
    return rest[:cut.start()] if cut else rest


def direction_problems(text: str, f: Facts, refs: list[str] | None = None,
                       dirs: dict[str, set[str]] | None = None) -> list[str]:
    """문장 하나의 방향 불일치 목록. refs 는 주장의 근거 키(문장에 키가 없어도 근거로 연결)."""
    dirs = flag_directions(f) if dirs is None else dirs
    probs: list[str] = []
    plain = KEY_RE.sub("", text)
    keys = set(KEY_RE.findall(text)) | set(refs or [])
    by_name = {n: (own, opp) for n, own, opp in DIRECTIONS}
    for k in sorted(keys):
        for name in dirs.get(k, ()):
            own, opp = by_name[name]
            if any(w in plain for w in opp) and not any(w in plain for w in own):
                probs.append(f"판정 방향 불일치: {k} 는 '{name}' 판정인데 반대 표현 사용")
    for k in sorted(keys):
        label = (f.items.get(k) or {}).get("label", "")
        for need, words in MISNAMED:
            if all(w in label for w in need):
                used = [w for w in words if w in plain and not re.search(re.escape(w) + r"\S{0,3}\s*(아님|아니|이 아)", plain)]
                if used:
                    probs.append(f"개념 오용: {k}({label})를 '{used[0]}'로 표현")
    for m in KEY_RE.finditer(text):
        it = f.items.get(m.group(1))
        if not it or it["unit"] not in SIGN_UNITS or not it["value"]:
            continue
        after = _after(text, m.end())
        pos, neg = any(w in after for w in POS_WORDS), any(w in after for w in NEG_WORDS)
        if it["value"] > 0 and neg and not pos or it["value"] < 0 and pos and not neg:
            probs.append(f"부호 불일치: {m.group(1)}={it['text']} 인데 '{after.strip()}'")
    inline = set(KEY_RE.findall(text))
    probs += ref_sign_problems(plain, f, [k for k in (refs or []) if k not in inline])
    return probs


# ------------------------------------------------------------ 숫자 없이 근거 키만 단 문장의 증감 서술
# 가이드 모드는 숫자를 빼고 '마이너스·플러스·증가' 처럼 말로 쓰는 경우가 많아, 위의 '키 바로 뒤' 점검에 걸리지 않습니다.
# (10/28 가이드 실행: 거래대금 배율 0.56배를 근거로 달고 '거래대금 증가'라고 쓴 문장이 통과)
# 근거 키 항목 이름의 앞부분(주어)을 문장에서 찾아, 그 뒤에 오는 증감 서술과 값의 방향을 비교합니다.
RATIO_DEADBAND = 0.05  # 배율이 1±이 값 안이면 방향 없음으로 봄
HIGH_WORDS = ("높", "많", "커", "크게 늘", "웃돌")
LOW_WORDS = ("낮", "적", "작", "줄", "밑돌")
SUBJECT_CUT = re.compile(r"\s*(?:\d|\(|최근|직전|변화|배율|강도|수량|금액|평균|비율)")


def _direction_of(it: dict) -> int:
    """항목 값의 방향: +1 증가 쪽, -1 감소 쪽, 0 방향 없음/판단 안 함."""
    v, unit = it.get("value"), it.get("unit")
    if v is None:
        return 0
    if unit in SIGN_UNITS:
        return (v > 0) - (v < 0)
    if unit == "배" and "배율" in it.get("label", ""):
        return 0 if abs(v - 1) < RATIO_DEADBAND else (1 if v > 1 else -1)
    return 0


def _subject(label: str) -> str:
    m = SUBJECT_CUT.search(label)
    return (label[:m.start()] if m else label).strip()


def ref_sign_problems(plain: str, f: Facts, refs: list[str]) -> list[str]:
    """근거 키(문장에 숫자로 안 나온 것)의 방향과 문장 서술의 방향이 반대인지. 주어가 겹치면 판단하지 않습니다."""
    cands = []
    for k in refs:
        it = f.items.get(k)
        if not it:
            continue
        d = _direction_of(it)
        subj = _subject(it["label"])
        if d and len(subj) >= 3:
            cands.append((k, it, d, subj))
    subjects = [s for *_, s in cands]
    probs = []
    for k, it, d, subj in cands:
        if subjects.count(subj) > 1 or plain.count(subj) != 1:  # 같은 주어가 여럿(5일·20일 등)이면 어느 값인지 모름
            continue
        after = _after(plain, plain.index(subj) + len(subj))
        up = any(w in after for w in POS_WORDS) or (it["unit"] == "배" and any(w in after for w in HIGH_WORDS))
        down = any(w in after for w in NEG_WORDS) or (it["unit"] == "배" and any(w in after for w in LOW_WORDS))
        if d > 0 and down and not up or d < 0 and up and not down:
            probs.append(f"부호 불일치: 근거 {k}={it['text']} 인데 '{subj}{after.rstrip()}'")
    return probs


# ------------------------------------------------------------ 기준선 판정과 다른 서술
OUTSIDE_WORDS = ("평소보다 높", "평소보다 낮", "평소보다 많", "평소보다 적", "평소보다 크", "평소보다 작",
                 "이례적", "급증", "급감")


def baseline_problems(text: str, refs: list[str] | None, baseline: list[dict] | None) -> list[str]:
    """기준선 비교에서 '평소 범위'로 판정된 신호를 '평소보다 높다·이례적'이라고 쓴 문장.

    (10/28 가이드 실행: 검색 관심도 배율 1.44배 → 기준선 판정 '평소 범위'인데 '평소보다 높은 편'으로 서술)"""
    if not baseline:
        return []
    plain = KEY_RE.sub("", text)
    keys = set(KEY_RE.findall(text)) | set(refs or [])
    probs = []
    for row in baseline:
        k = row.get("measure")
        if k not in keys or row.get("status") != "평소 범위":
            continue
        name = str(row.get("signal", ""))
        head = name.split("(")[0].split()[0] if name else ""
        if head and head not in plain:   # 같은 문장의 다른 신호에 대한 서술일 수 있음
            continue
        start = plain.index(head) if head else 0
        seg = plain[start:start + len(head) + 20]   # 신호 이름 뒤 20자 안의 서술만 봄
        used = [w for w in OUTSIDE_WORDS if w in seg]
        if used:
            probs.append(f"기준선 판정 불일치: {name}({k})는 '평소 범위'인데 '{used[0]}' 서술")
    return probs
