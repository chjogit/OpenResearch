"""v0.38 T2 릴리스 되짚기: 보관본(before/)에서 패치를 차례로 돌려 지금 엔진 파일과 글자까지 같은지 본다. 엔진 파일은 고치지 않는다(임시 폴더에서만).
쓰는 법: python verify_rebuild.py <modu-research-nodes 경로>      (이 파일이 있는 릴리스 폴더 기준)
순서가 곧 적용 순서다. 새 파일은 new/ 에서, 이름 바꿈 전 단계의 autocheck.py 는 stages/ 에서 가져온다."""
import filecmp, shutil, subprocess, sys, tempfile
from pathlib import Path

R = Path(__file__).resolve().parent
N = Path(sys.argv[1]).resolve()
STEPS = ['patch_t2_1', 'patch_t2_2_web', 'patch_t2_2b_web', 'patch_t2_2c_web', 'patch_verify_guide', 'patch_t2_1b',
         ('copy', 'stages/autocheck_T2-1b.py', 'mrn/autocheck.py'),          # 이름 바꿈(patch_names2)이 고치는 대상
         'patch_names', 'patch_names2', 'patch_modebar', 'patch_t2_3a', 'patch_t2_3b', 'patch_t2_3c', 'patch_t2_4a', 'patch_t2_3e', 'patch_t2_3f_web', 'patch_t2_4b', 'patch_t2_4d', 'patch_t2_4d2_web', 'patch_t2_4e', 'patch_t2_4e_closeout', 'patch_t2_4f', 'patch_t2_5a']
NEW_ONLY = ['mrn/filing_grade.py', 'mrn/filing_grades.json', 'mrn/filing2.py', 'mrn/dartsamples.py', 'tests/test_v038_reduction.py',
            'tests/test_v038_autocheck.py', 'tests/test_v038_autocheck_b.py', 'tests/test_v038_grade.py', 'tests/test_v038_filing2.py', 'mrn/prob.py', 'tests/test_v038_prob.py', 'mrn/filing3.py', 'tests/test_v038_rights.py', 'tests/test_v038_t2_4a.py', 'tests/test_v038_convertible.py', 'tests/test_v038_cvadjust.py', 'mrn/tradecal.py', 'mrn/krx_holidays.json', 'tests/test_v038_tradecal.py', 'tests/test_v038_t2_4d.py', 'tests/test_v038_t2_4e.py', 'tests/test_v038_t2_4f.py', 'tests/test_v038_t2_5.py']   # 패치가 아니라 통째로 더한 파일

with tempfile.TemporaryDirectory() as tmp:
    W = Path(tmp)
    shutil.copytree(R / 'before', W, dirs_exist_ok=True)
    for s in STEPS:
        if isinstance(s, tuple):
            (W / s[2]).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(R / s[1], W / s[2]); continue
        r = subprocess.run([sys.executable, str(R / f'{s}.py'), str(W)], capture_output=True, text=True, encoding='utf-8')
        if r.returncode != 0:
            print(f'멈춤: {s} 실패\n{r.stdout}{r.stderr}'); sys.exit(1)
    bad = [str(p.relative_to(W)) for p in sorted(W.rglob('*')) if p.is_file() and not filecmp.cmp(p, N / p.relative_to(W), shallow=False)]
    n = sum(1 for p in W.rglob('*') if p.is_file())
    newbad = [f for f in NEW_ONLY if not (R / 'new' / f).exists() or not filecmp.cmp(R / 'new' / f, N / f, shallow=False)]
    print(f'패치로 다시 만든 파일 {n}개 중 지금 엔진과 다른 것 {len(bad)}개' + (': ' + ', '.join(bad) if bad else ''))
    print(f'통째로 더한 파일 {len(NEW_ONLY)}개 중 new/ 와 다른 것 {len(newbad)}개' + (': ' + ', '.join(newbad) if newbad else ''))
    sys.exit(1 if bad or newbad else 0)
