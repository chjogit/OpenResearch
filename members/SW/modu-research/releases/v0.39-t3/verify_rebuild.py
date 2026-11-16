"""v0.39 T3 릴리스 되짚기: 보관본(before/)에서 패치를 차례로 돌려 지금 엔진 파일과 글자까지 같은지 본다. 엔진 파일은 고치지 않는다(임시 폴더에서만).
쓰는 법: python verify_rebuild.py <modu-research-nodes 경로>. 새 파일은 new/ 와 대조한다."""
import filecmp, shutil, subprocess, sys, tempfile
from pathlib import Path

R = Path(__file__).resolve().parent
N = Path(sys.argv[1]).resolve()
STEPS = ['patch_t3_1', 'patch_t3_2a', 'patch_t3_2b', 'patch_t3_2c']
NEW_ONLY = ['mrn/surge.py', 'tests/test_v039_surge.py', 'mrn/filing4.py', 'tests/test_v039_supply.py']

with tempfile.TemporaryDirectory() as tmp:
    W = Path(tmp)
    shutil.copytree(R / 'before', W, dirs_exist_ok=True)
    for s in STEPS:
        r = subprocess.run([sys.executable, str(R / f'{s}.py'), str(W)], capture_output=True, text=True, encoding='utf-8')
        if r.returncode != 0:
            print(f'멈춤: {s} 실패\n{r.stdout}{r.stderr}'); sys.exit(1)
    bad = [str(p.relative_to(W)) for p in sorted(W.rglob('*')) if p.is_file() and not filecmp.cmp(p, N / p.relative_to(W), shallow=False)]
    n = sum(1 for p in W.rglob('*') if p.is_file())
    newbad = [f for f in NEW_ONLY if not (R / 'new' / f).exists() or not filecmp.cmp(R / 'new' / f, N / f, shallow=False)]
    print(f'패치로 다시 만든 파일 {n}개 중 지금 엔진과 다른 것 {len(bad)}개' + (': ' + ', '.join(bad) if bad else ''))
    print(f'통째로 더한 파일 {len(NEW_ONLY)}개 중 new/ 와 다른 것 {len(newbad)}개' + (': ' + ', '.join(newbad) if newbad else ''))
    sys.exit(1 if bad or newbad else 0)
