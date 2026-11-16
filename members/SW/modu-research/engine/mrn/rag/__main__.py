"""python -m mrn.rag build|embed|eval  (index folder defaults to data/rag)."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['build', 'embed', 'eval'])
    ap.add_argument('--src', default=str(ROOT.parent / '_sources' / 'dart_full'))
    ap.add_argument('--out', default=os.environ.get('MODU_NODES_RAG_DIR', str(ROOT / 'data' / 'rag')))
    ap.add_argument('--model', default=os.environ.get('MODU_NODES_EMBED_MODEL', 'embeddinggemma:300m'))
    ap.add_argument('--ollama', default=os.environ.get('MODU_NODES_OLLAMA', 'http://127.0.0.1:11434'))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.cmd == 'build':
        from .ingest import build
        chunks, man = build(a.src)
        Path(a.out, 'chunks.json').write_text(json.dumps(chunks, ensure_ascii=False), encoding='utf-8')
        Path(a.out, 'manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
        vj = Path(a.out, 'vectors.json')
        if vj.exists() and json.loads(vj.read_text(encoding='utf-8')).get('corpusHash') != man['corpusHash']:
            print('기존 벡터는 새 색인과 맞지 않아 사용되지 않습니다. embed 를 다시 실행하세요.')
        print(f"chunks={man['chunks']} files={len(man['files'])} rejected={man['rejected']} corpus={man['corpusHash'][:16]}")
    elif a.cmd == 'embed':
        from .search import embed_index
        shape = embed_index(a.out, a.ollama, a.model, progress=lambda d, n: print(f'\r{d}/{n}', end='', flush=True))
        print(f'\nvectors={shape} model={a.model}')
    else:
        from .search import Index
        from .evaluate import run
        idx = Index(a.out)
        for syn in (False, True):
            r = run(idx, synonyms=syn)
            print(f"mode={r['mode']} synonyms={syn}", json.dumps(r['summary'], ensure_ascii=False))
        r = run(idx)
        for x in r['rows']:
            print(x['id'], x['first_rank'], x['found@10'], x['question'][:40])


if __name__ == '__main__':
    sys.exit(main())
