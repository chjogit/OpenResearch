"""모드별 프롬프트 (기초기획서 R2 3.4 '프롬프트: expert.md / guide.md 분기').

prompts/expert.md, prompts/guide.md 를 읽어 '## 공통'과 '## 에이전트 <번호>' 절을 합칩니다.
문구를 고칠 때는 코드가 아니라 이 두 파일을 고칩니다.
"""
from __future__ import annotations

import os
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


# #18 청크 인용 보강 (CH_CHUNK_CITE=boost, 기본 off). 청크 근거 모드(CH_RAG_RERANK=on|chunk)일 때만 적용.
# 꺼져 있으면 프롬프트·검사가 #12 와 같음. 숫자 규칙·목록 밖 chunk_id 거절·개인 의견 제한·추천/목표주가 금지는 그대로.
def chunk_boost_enabled() -> bool:
    return os.getenv("CH_CHUNK_CITE", "off").strip().lower() in ("boost", "on")


CHUNK_BOOST_RULE = """[청크 인용 보강]
- [근거 청크] 각 줄 앞의 'D번호 · chunk_id' 쌍이 인용 단위입니다. 청크 내용을 쓴 주장에는 근거에 그 D번호를, "chunkId" 에 그 chunk_id 를 함께 넣으십시오.
- 관점과 관련된 청크가 있으면 주장·반대근거 중 2개 이상(주로 '해석')은 청크를 근거로 쓰십시오. 숫자 장부 키와 청크 D번호를 한 주장에 함께 써도 됩니다(숫자는 장부 키, 사건·맥락은 청크).
- 발췌의 [수치] 는 가린 숫자입니다. 값을 추정하거나 다시 쓰지 말고 '무슨 일이 있었는지'만 쓰십시오.
- 관련 청크가 없으면 억지로 인용하지 말고 미확인에 '근거 청크 없음'이라고 적으십시오."""

CHUNK_BOOST_EXAMPLE = ('[청크 인용 예시 — 형식만 참고, 키·chunk_id 는 실제 목록의 것을 쓰십시오] '
                       '{"문장": "외국인 순매수 확대 보도가 있어 수급 개선 판정과 같은 방향이다.", "구분": "해석", '
                       '"근거": ["S3", "D2"], "chunkId": [123]}')

CHUNK_BOOST_MISSING = "청크 근거 주장 없음 (관련 청크가 있으면 해석 주장 2개 이상에 D번호와 chunkId 를 붙이기, 없으면 미확인에 '근거 청크 없음')"
