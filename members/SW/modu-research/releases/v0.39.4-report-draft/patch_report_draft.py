"""v0.39.4 근거 고정 보고서 초안 — server.py 에 등록 두 줄 + 새 파일. 쓰는 법: python patch_report_draft.py <modu-research-nodes 경로>"""
import shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; N = Path(sys.argv[1])
OLD = "    _rd_register(app, store)\n    return app\n"
NEW = ("    _rd_register(app, store)\n"
       "    from .report_draft_api import register as _draft_register   # v0.39.4 근거 고정 보고서 초안\n"
       "    _draft_register(app, store, owner)\n    return app\n")
p = N / 'mrn/server.py'; s = p.read_text(encoding='utf-8')
if 'v0.39.4 근거 고정 보고서 초안' in s:
    print('mrn/server.py: 이미 적용됨')
elif s.count(OLD) != 1:
    raise SystemExit(f'mrn/server.py: 고칠 자리를 정확히 하나 찾지 못함({s.count(OLD)}) — 아무것도 바꾸지 않음')
else:
    p.write_text(s.replace(OLD, NEW), encoding='utf-8', newline='\n'); print('mrn/server.py: 고침')
for f in ['mrn/report_draft.py', 'mrn/report_draft_api.py', 'tests/test_v0394_report_draft.py']:
    shutil.copyfile(HERE / 'new' / f, N / f); print('새 파일:', f)
