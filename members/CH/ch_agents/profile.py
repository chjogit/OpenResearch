"""사용자 프로필: 숙련도 3단계 × 성향 2가지 (팀 회의 2026-10-28 결정).

- 숙련도(level): L1 입문자, L2 보고서 작성이 낯선 투자자, L3 프로 애널리스트 → 설명의 깊이만 바꿈
- 성향(stance): defensive 방어, aggressive 공격 → 읽는 순서만 바꿈 (방어: 하방 위험부터, 공격: 변화 신호부터)

프로필은 에이전트 출력(데이터 계약)에 들어가지 않습니다. 같은 계약 하나를 여러 프로필로 보여 주므로
수치·근거·판정은 프로필과 무관합니다(renderer.content_set 으로 검사).

SH 페르소나(members/SH/sh_agents/personas.py, L1~L4 × A/C)와 값을 주고받을 수 있게 별칭을 받습니다:
A·적극 → aggressive, C·신중 → defensive, L4 → L3.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

PROFILE_VERSION = "1.0"


class Level(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class Stance(StrEnum):
    DEFENSIVE = "defensive"
    AGGRESSIVE = "aggressive"


LEVEL_NAMES = {Level.L1: "입문자", Level.L2: "보고서 작성이 낯선 투자자", Level.L3: "프로 애널리스트"}
STANCE_NAMES = {Stance.DEFENSIVE: "방어", Stance.AGGRESSIVE: "공격"}

_LEVEL_ALIAS = {"L1": Level.L1, "L2": Level.L2, "L3": Level.L3, "L4": Level.L3,
                "입문": Level.L1, "입문자": Level.L1, "기초": Level.L2, "중급": Level.L3, "고급": Level.L3,
                "프로": Level.L3, "전문가": Level.L3}
_STANCE_ALIAS = {"defensive": Stance.DEFENSIVE, "방어": Stance.DEFENSIVE, "방어적": Stance.DEFENSIVE,
                 "C": Stance.DEFENSIVE, "신중": Stance.DEFENSIVE, "신중형": Stance.DEFENSIVE,
                 "aggressive": Stance.AGGRESSIVE, "공격": Stance.AGGRESSIVE, "공격적": Stance.AGGRESSIVE,
                 "A": Stance.AGGRESSIVE, "적극": Stance.AGGRESSIVE, "적극형": Stance.AGGRESSIVE}


@dataclass(frozen=True)
class UserProfile:
    level: Level = Level.L2
    stance: Stance = Stance.DEFENSIVE

    def __post_init__(self):
        object.__setattr__(self, "level", parse_level(self.level))
        object.__setattr__(self, "stance", parse_stance(self.stance))

    @property
    def label(self) -> str:
        return f"{LEVEL_NAMES[self.level]} · {STANCE_NAMES[self.stance]}"

    def to_dict(self) -> dict:
        return {"level": self.level.value, "stance": self.stance.value, "version": PROFILE_VERSION}

    @classmethod
    def from_dict(cls, d: dict | None) -> UserProfile:
        d = d or {}
        return cls(level=d.get("level", Level.L2), stance=d.get("stance", Stance.DEFENSIVE))


def parse_level(v) -> Level:
    key = v.value if isinstance(v, StrEnum) else str(v).strip()
    if key in _LEVEL_ALIAS:
        return _LEVEL_ALIAS[key]
    raise ValueError(f"숙련도는 L1·L2·L3 중 하나여야 합니다: {v!r}")


def parse_stance(v) -> Stance:
    key = v.value if isinstance(v, StrEnum) else str(v).strip()
    if key in _STANCE_ALIAS:
        return _STANCE_ALIAS[key]
    raise ValueError(f"성향은 defensive(방어)·aggressive(공격) 중 하나여야 합니다: {v!r}")


ALL_PROFILES = tuple(UserProfile(lv, st) for lv in Level for st in Stance)
