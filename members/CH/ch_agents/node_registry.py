"""노드 runner 등록을 한곳에서 (#25, #24 PM 결정 ②).

flow_nodes·macro_nodes·sentiment_nodes 는 import 할 때 자기 runner 를 `nodes.RUNNERS` 에 등록한다.
어느 진입점에서 실행해도 같은 노드가 등록되도록, 노드 실행 틀(`nodes.run_agent_nodes`)이 시작할 때 이 함수를 부른다.
"""
from __future__ import annotations

NODE_MODULES = ("macro_nodes", "flow_nodes", "sentiment_nodes")   # 에이전트 3·4·6 순서


def ensure_registered() -> list[str]:
    """세 모듈을 import 해 runner 가 등록되게 한다(이미 import 됐으면 아무 일도 없음). 등록된 노드 ID 를 돌려준다."""
    import importlib

    from . import nodes

    for name in NODE_MODULES:
        importlib.import_module(f"{__package__}.{name}")
    return sorted(nodes.RUNNERS)
