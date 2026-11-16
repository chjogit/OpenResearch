"""사업보고서 원문 색인을 서버(문서·재무 화면)와 노드(T02)가 함께 쓴다."""
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_LOCK = threading.Lock()
_CACHE = {}


class RagUnavailable(RuntimeError):
    pass


def paths(data_dir):
    rag_dir = os.environ.get('MODU_NODES_RAG_DIR') or os.path.join(str(data_dir), 'rag')
    rag_src = os.environ.get('MODU_NODES_DART_FULL') or str(ROOT.parent / '_sources' / 'dart_full')
    return rag_dir, rag_src


def get_index(data_dir, rebuild=False):
    from .search import Index
    from .ingest import PARSER_VERSION, build
    rag_dir, rag_src = paths(data_dir)
    with _LOCK:
        if rag_dir in _CACHE and not rebuild:
            return _CACHE[rag_dir]
        mp = os.path.join(rag_dir, 'manifest.json')
        stale = os.path.exists(mp) and json.loads(Path(mp).read_text(encoding='utf-8')).get('parser') != PARSER_VERSION
        if rebuild or stale or not os.path.exists(os.path.join(rag_dir, 'chunks.json')):
            if not os.path.isdir(rag_src):
                raise RagUnavailable(f'사업보고서 원문 폴더가 없습니다: {rag_src}')
            chunks, man = build(rag_src)
            os.makedirs(rag_dir, exist_ok=True)
            with open(os.path.join(rag_dir, 'chunks.json'), 'w', encoding='utf-8') as f:
                json.dump(chunks, f, ensure_ascii=False)
            with open(os.path.join(rag_dir, 'manifest.json'), 'w', encoding='utf-8') as f:
                json.dump(man, f, ensure_ascii=False, indent=1)
        _CACHE[rag_dir] = Index(rag_dir)
        return _CACHE[rag_dir]
