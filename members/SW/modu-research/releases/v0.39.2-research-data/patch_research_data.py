"""v0.39.2 연구용 데이터(KIS 현재가 보여 주기 · 컨센서스) — server.py 에 등록 두 줄만 더하고, 새 파일은 new/ 에서 복사.
쓰는 법: python patch_research_data.py <modu-research-nodes 경로>. 고칠 곳을 먼저 확인, 못 찾으면 아무것도 안 바꿈, 두 번 돌려도 같음."""
import shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; N = Path(sys.argv[1])
OLD = "    _autocheck_register(app, store, owner)\n    return app\n"
NEW = ("    _autocheck_register(app, store, owner)\n"
       "    from .research_data_api import register as _rd_register     # v0.39.2 연구용 데이터(시세 보여 주기·컨센서스, 스위치)\n"
       "    _rd_register(app, store)\n    return app\n")
p = N / 'mrn/server.py'; s = p.read_text(encoding='utf-8')
if 'v0.39.2 연구용 데이터' in s:
    print('mrn/server.py: 이미 적용됨')
elif s.count(OLD) != 1:
    raise SystemExit(f'mrn/server.py: 고칠 자리를 정확히 하나 찾지 못함({s.count(OLD)}) — 아무것도 바꾸지 않음')
else:
    p.write_text(s.replace(OLD, NEW), encoding='utf-8', newline='\n'); print('mrn/server.py: 고침')
for f in ['mrn/research_data.py', 'mrn/research_data_api.py', 'tests/test_v0392_research_data.py']:
    if (HERE / 'new' / f).exists():
        shutil.copyfile(HERE / 'new' / f, N / f); print('새 파일:', f)
