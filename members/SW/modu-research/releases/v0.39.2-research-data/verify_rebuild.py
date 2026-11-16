"""v0.39.2 되짚기: before/ 에서 패치를 돌려 지금 엔진 파일과 글자까지 같은지(임시 폴더). 쓰는 법: python verify_rebuild.py <modu-research-nodes 경로>"""
import filecmp, shutil, subprocess, sys, tempfile
from pathlib import Path
R = Path(__file__).resolve().parent; N = Path(sys.argv[1]).resolve()
NEW_ONLY = ['mrn/research_data.py', 'mrn/research_data_api.py', 'tests/test_v0392_research_data.py']
with tempfile.TemporaryDirectory() as tmp:
    W = Path(tmp); shutil.copytree(R / 'before', W, dirs_exist_ok=True); (W / 'tests').mkdir(exist_ok=True)
    r = subprocess.run([sys.executable, str(R / 'patch_research_data.py'), str(W)], capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        print('멈춤: 패치 실패\n' + r.stdout + r.stderr); sys.exit(1)
    bad = [str(p.relative_to(W)) for p in sorted(W.rglob('*')) if p.is_file() and not filecmp.cmp(p, N / p.relative_to(W), shallow=False)]
    print(f'패치로 다시 만든 파일 중 지금 엔진과 다른 것 {len(bad)}개' + (': ' + ', '.join(bad) if bad else ''))
    sys.exit(1 if bad else 0)
