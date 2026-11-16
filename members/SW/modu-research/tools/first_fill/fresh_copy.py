"""처음부터 시험 준비 — 팀원이 공용 저장소에서 받게 될 것과 같은 모양의 「깨끗한 작업 폴더」를 PM PC에 하나 만든다.
원본 폴더는 읽기만 한다. 자료(_sources)·키(local-env.cmd)·가상환경·DB·결과물은 복사하지 않는다(다음 PR 묶음 pr_pack 과 같은 규칙).
쓰는 법: python fresh_copy.py [대상 폴더]   (기본: 원본 옆 「모두의리서치_처음부터_<시각>」)"""
import os, shutil, sys
from datetime import datetime
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]            # 2차_모두의리서치_cluade
ENGINE_KEEP = ['mrn', 'tests', 'web', 'scripts', 'docs', 'vendor', 'reused', 'README.md', 'pyproject.toml',
               'setup.cmd', 'start.cmd', 'stop.cmd', 'test.cmd', 'prepare-rag.cmd', 'apply-quarter.cmd', 'local-env.example.cmd']
TOOLS_KEEP = ['first_fill', 'price_refresh', 'flow_refresh', 'backup']
SKIP_DIRS = {'__pycache__', '.pytest_cache', '.venv', '.uv-cache', 'node_modules', '.git', 'data', 'out', '_to_delete', 'before'}
SKIP_FILES = {'local-env.cmd', '.env', 'last-result.txt', 'probe-result.txt'}
SKIP_SUFFIX = ('.pyc', '.log', '.bak', '.sqlite', '.sqlite3', '.db', '.zip', '.pdf', '.part')


def copy_tree(src, dst, keep):
    n = 0
    for k in keep:
        s = src / k
        if s.is_file():
            (dst / k).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(s, dst / k); n += 1; continue
        for dp, dn, fn in os.walk(s):
            dn[:] = [d for d in dn if d not in SKIP_DIRS or (d == 'data' and Path(dp).name == 'tests')]
            for f in fn:
                if f in SKIP_FILES or f.lower().endswith(SKIP_SUFFIX):
                    continue
                p = Path(dp) / f; out = dst / p.relative_to(src)
                out.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, out); n += 1
    return n


def main():
    stamp = datetime.now().strftime('%m%d_%H%M')
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC.parent / f'모두의리서치_처음부터_{stamp}'
    if target.exists():
        print(f'[멈춤] {target} 가 이미 있어요. 덮지 않습니다.'); return 1
    root = target / 'modu-research'
    n = copy_tree(SRC / 'modu-research-nodes', root / 'engine', ENGINE_KEEP)
    n += copy_tree(SRC / '_tools', root / 'tools', TOOLS_KEEP)
    shutil.copy2(SRC / '_tools' / 'pr_pack' / 'SW_GUIDE.md', target / '따라하기_안내서.md')
    # 확인: 키·자료가 섞이지 않았는지
    bad = [p for p in target.rglob('*') if p.name in ('local-env.cmd', '.env') or '_sources' in p.parts]
    if bad:
        print('[멈춤] 키·자료 파일이 섞였어요:', bad[:3]); return 2
    print(f'만든 폴더: {target}')
    print(f'담은 파일 {n}개 · 자료(_sources)·키(local-env.cmd)·가상환경 없음 = 팀원이 받는 것과 같은 출발점')
    print('다음: 이 폴더의 따라하기_안내서.md 1단계부터(modu-research\\engine\\setup.cmd)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
