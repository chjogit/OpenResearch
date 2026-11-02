"""모드별 프롬프트 (기초기획서 R2 3.4 '프롬프트: expert.md / guide.md 분기').

prompts/expert.md, prompts/guide.md 를 읽어 '## 공통'과 '## 에이전트 <번호>' 절을 합칩니다.
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
             s.get("공통", ""), s.get(f"에이전트 {agent_id}", "")]
    return "\n".join(p for p in parts if p)


# R4-2 청크 근거 런타임 지시문 (11/2 사용자 지시서 원문 그대로). CH_RAG_RERANK=on 으로 청크 근거가 붙을 때만 프롬프트에 들어감
CHUNK_RUNTIME_RULE = """아래 [근거 청크] 에서만 정성 근거를 쓴다. 문장마다 해당 chunk_id 를 붙인다.
청크에 없는 사실은 쓰지 않는다. 청크 속 숫자는 옮기지 않고, 숫자는 [장부] 키로만 인용한다.
청크끼리 결론이 엇갈리면 둘 다 적고 반대 근거(role=counter)로 표시한다.
청크가 부족하면 '근거 부족'이라고 쓴다."""

# 출력 형식 보충 (지시문을 JSON 필드로 옮기는 방법). 원문 지시문과 별개로 둠
CHUNK_OUTPUT_RULE = ("[근거 청크 사용법] 청크를 근거로 쓴 주장·반대근거 객체에는 \"chunkId\": [chunk_id 정수] 를 붙이고, "
                     "근거 키로 그 청크의 D번호도 함께 쓰십시오. 목록에 없는 chunk_id 를 쓴 문장은 삭제됩니다. "
                     "청크 속 숫자를 옮긴 문장도 삭제됩니다. '개인 의견' 청크는 사실 주장의 근거가 될 수 없습니다. "
                     "근거 청크가 하나도 없으면 청크 근거 주장을 쓰지 말고 미확인에 '근거 청크 없음'이라고 적으십시오.")
