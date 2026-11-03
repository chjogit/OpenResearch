"""#25 노드 runner 등록은 한곳(node_registry)에서."""
import subprocess
import sys
from pathlib import Path

from ch_agents import node_registry, nodes

ROOT = Path(__file__).resolve().parents[1]


def test_ensure_registered_gives_all_six_nodes():
    assert node_registry.ensure_registered() == ["N05", "N06", "N07", "N08", "N11", "N12"]


def test_any_entry_point_registers_same_nodes_in_fresh_process():
    for first in ("ch_agents.nodes", "ch_agents.flow_nodes", "ch_agents.sentiment_nodes"):
        code = ("import importlib; m = importlib.import_module(%r); from ch_agents import nodes; "
                "nodes.run_agent_nodes(3, '005930', '2026-10-26', runners={}, available=set()); "
                "print(sorted(nodes.RUNNERS))" % first)
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr[-400:]
        assert out.stdout.strip() == "['N05', 'N06', 'N07', 'N08', 'N11', 'N12']", (first, out.stdout)
