"""모드별 프롬프트 (기초기획서 R2 3.4 '프롬프트: expert.md / guide.md 분기').

prompts/expert.md, prompts/guide.md 를 읽어 '## 공통'과 '## A<번호>' 절을 합칩니다.
문구를 고칠 때는 코드가 아니라 이 두 파일을 고칩니다.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent / "prompts"
MODES = ("expert", "guide")


@lru_cache(maxsize=None)
def _sections(mode: str) -> dict[str, str]:
    if mode not in MODES:
        raise ValueError(f"mode 는 {MODES} 중 하나입니다 (받은 값: {mode!r})")
    text = (DIR / f"{mode}.md").read_text(encoding="utf-8")
    out, name, buf = {}, "_head", []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            out[name] = "\n".join(buf).strip()
            name, buf = m.group(1), []
        else:
            buf.append(line)
    out[name] = "\n".join(buf).strip()
    return out


def mode_guide(mode: str, agent_id: int) -> str:
    s = _sections(mode)
    title = s.get("_head", "").splitlines()[0].lstrip("# ").strip() if s.get("_head") else mode
    parts = [f"{title}: " + " ".join(ln.strip() for ln in s.get("_head", "").splitlines()[1:] if ln.strip()),
             s.get("공통", ""), s.get(f"A{agent_id}", "")]
    return "\n".join(p for p in parts if p)
