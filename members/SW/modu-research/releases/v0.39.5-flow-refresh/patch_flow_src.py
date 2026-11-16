"""v0.39.5 엔진: 수급 사본에 KIS로 보충한 날(source='kis_investor')을 출처에 표시(연구용 스위치 MODU_PRICE_KIS=0 이면 그 행도 안 씀).
외국인 보유율이 비어 있는 날(외국인 한도 종목)이 있으면 보유율 문장에 그 값의 실제 날짜를 밝힘(nodes.py N07).
쓰는 법: python patch_flow_src.py <modu-research-nodes 경로>. 고칠 곳을 모두 먼저 확인, 못 찾으면 아무것도 안 바꿈, 두 번 돌려도 같음."""
import shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; N = Path(sys.argv[1]); MARK = 'v0.39.5'
EDITS = {
    'mrn/market.py': [
        ("    flows, fmeta, later = _ticker_rows(root, man, 'investor_flow_daily', company, last)\n",
         "    flows, fmeta, later = _ticker_rows(root, man, 'investor_flow_daily', company, last)\n"
         "    if not _PS.ok('kis'):   # v0.39.5 연구용 스위치(MODU_PRICE_KIS=0)면 KIS 수급 보충 행도 쓰지 않음\n"
         "        flows = [r for r in flows if r.get('source') != 'kis_investor']\n", 1),
        ("    src = {'flows': _src(root, man, fmeta, 'core.investor_flow_daily', '네이버 금융 투자자별 매매(포털 수집) — Neon 공용 DB 경유')}\n",
         "    nkf = sum(1 for r in flows if r.get('source') == 'kis_investor')   # v0.39.5\n"
         "    src = {'flows': _src(root, man, fmeta, 'core.investor_flow_daily', '네이버 금융 투자자별 매매(포털 수집) — Neon 공용 DB 경유'\n"
         "                         + (f' + 한국투자증권 투자자별 매매(kis) {nkf}거래일 보충(연구용·재배포 계약 전)' if nkf else ''))}\n"
         "    src['flows']['kis_rows'] = nkf\n", 1),
        ("        'notes': ['투자자별 순매수는 포털(네이버)에서 수집한 값이며, 거래소(KRX) 공식 자료와 아직 대조하지 않았습니다.',\n",
         "        'notes': ['투자자별 순매수는 포털(네이버)에서 수집한 값이며, 거래소(KRX) 공식 자료와 아직 대조하지 않았습니다.'\n"
         "                  + (f' 최근 {nkf}거래일은 한국투자증권 조회값으로 보충했습니다(겹치는 날 네이버 값과 주 단위까지 같음을 확인한 회사만).' if nkf else ''),\n", 1),
    ],
    'mrn/nodes.py': [
        ("        F.append({'name': '외국인 보유율', 'claim': txt, 'kind': 'derived', 'as_of': d, 'formula': '보유율(포털 수집값)의 차이'})\n",
         "        if hp[-1][0] != d:   # v0.39.5 보유율이 빈 날(외국인 한도 종목의 KIS 보충분)이 있으면 값의 실제 날짜를 밝힘\n"
         "            txt = f'{hp[-1][0]} 기준 ' + txt\n"
         "        F.append({'name': '외국인 보유율', 'claim': txt, 'kind': 'derived', 'as_of': hp[-1][0], 'formula': '보유율(포털 수집값)의 차이'})\n", 1),
    ],
}
DONE = {'mrn/market.py': 'kis_investor', 'mrn/nodes.py': 'v0.39.5 보유율'}
todo, miss = [], []
for f, eds in EDITS.items():
    s = (N / f).read_text(encoding='utf-8')
    if DONE[f] in s:
        print(f'{f}: 이미 적용됨'); continue
    for old, new, want in eds:
        if s.count(old) != want:
            miss.append(f'{f}: {old[:50]!r} ({s.count(old)}/{want})'); continue
        s = s.replace(old, new)
    todo.append((f, s))
if miss:
    raise SystemExit('고칠 자리를 못 찾아 아무것도 바꾸지 않음:\n  ' + '\n  '.join(miss))
for f, s in todo:
    (N / f).write_text(s, encoding='utf-8', newline='\n'); print(f'{f}: 고침')
for f in ['tests/test_v0395_flow_src.py']:
    if (HERE / 'new' / f).exists():
        shutil.copyfile(HERE / 'new' / f, N / f); print('새 파일:', f)
