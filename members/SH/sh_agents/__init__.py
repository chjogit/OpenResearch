"""SH 담당 두 Agent(산업·사업모델, 기술적 분석) 패키지.

공용 코드(agent.llm·agent.config 등)를 쓰기 위해 저장소 루트를 import 경로에 추가합니다.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))
