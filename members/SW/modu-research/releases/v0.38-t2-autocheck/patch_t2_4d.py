"""v0.38 T2-4d 출처 표시(P04-2): 답마다 「언제·어디서·어떻게 왔나」와 이용 범위를 보인다. 더하기만(기존 칸은 그대로).
- 공시 원문: 접수번호(원문 링크), 받은 시각, 받은 방법(접수번호로 직접 / 대량 받기 / 자동 확인), 앱이 공시 목록에서 처음 본 시각(자동 확인 기록, 없으면 「기록 없음」).
- J23: 「앱이 처음 본 시각」은 앱 기록이라 시간이 지나면 생길 수 있다 → 단계 결과(지문을 매기는 값)에 넣지 않고 답을 보일 때 붙인다. 다시 계산해도 같은 결과.
- 시세 등 사본: 사본 이름, 자료 수집 시각(가장 늦은 줄), 이용 범위. 거래 상태(거래정지 등)는 자료가 없어 표시하지 않는다고 적는다.
- PM 결정 ③: 공시 숫자 화면(카드 filing)만 「사실 → 계산 → 추정」 순서. 다른 카드는 그대로(추정 먼저).
고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
EDITS = {
    'mrn/filing.py': ("'fetched_how'", [
        ("'url': d['url'], 'sha256': d['sha256'], 'parsed': parse(d['kind'], doc),",
         "'url': d['url'], 'sha256': d['sha256'], 'fetched_at': d.get('fetched_at'), 'fetched_how': d.get('added_by') or 'bulk',   # v0.38 T2-4d 출처 표시\n"
         "           'parsed': parse(d['kind'], doc),"),
    ]),
    'mrn/autocheck.py': ("def seen_info", [
        ("def board_view(store, tickers, now=None):\n",
         "def seen_info(store, rcept_no):\n"
         "    \"\"\"v0.38 T2-4d 출처 표시: 이 공시를 앱이 공시 목록에서 처음 본 시각(자동 확인 기록). 기록이나 표가 없으면 None — 지어내지 않는다.\"\"\"\n"
         "    import sqlite3\n"
         "    if store is None:\n"
         "        return None\n"
         "    try:\n"
         "        with store.lock, store.connect() as c:\n"
         "            r = c.execute('SELECT first_seen_at, prev_checked_at, first_check FROM filing_seen WHERE rcept_no=?', (rcept_no,)).fetchone()\n"
         "    except sqlite3.OperationalError:                       # 자동 확인을 한 번도 켜지 않아 표가 없음\n"
         "        return None\n"
         "    return {'first_seen_at': r['first_seen_at'], 'prev_checked_at': r['prev_checked_at'], 'first_check': bool(r['first_check'])} if r else None\n"
         "\n\n"
         "def board_view(store, tickers, now=None):\n"),
    ]),
    'mrn/nodes.py': ("how=f.get('fetched_how')", [
        ("    payload = {**{k: v for k, v in f.items() if k not in ('docs', 'kind')}, 'filing_kind': f['kind'],",
         "    src['dart_docs'].update(rcept_no=no, url=f['url'], fetched_at=f.get('fetched_at'), how=f.get('fetched_how'))   # v0.38 T2-4d 출처 표시(더하기만). 앱이 처음 본 시각은 답을 보일 때 붙임(J23)\n"
         "    payload = {**{k: v for k, v in f.items() if k not in ('docs', 'kind')}, 'filing_kind': f['kind'],"),
    ]),
}
EDITS['mrn/easy.py'] = ("TRADE_STATUS_NOTE", [
    ("def _sources(p):\n    out = []\n",
     "HOW = {'manual': '접수번호로 직접 받음', 'bulk': '대량 받기로 받음', 'auto': '자동 확인이 받음'}           # v0.38 T2-4d 출처 표시\n"
     "USE = {'official': '공식 공개 자료(출처를 밝혀 인용)', 'public': '공공데이터 — 이용 조건(상업적 이용·재배포) 확인 전',\n"
     "       'portal': '포털 수집 — 연구용 한정(공개판에서 뺌)', 'unofficial': '비공식 — 참고용', 'rule_derived': '앱이 규칙으로 계산한 값',\n"
     "       'derived': '앱이 계산한 값', 'registered': '등록 정보'}\n"
     "TRADE_STATUS_NOTE = '거래 상태(거래정지·관리종목·투자경고 등)는 아직 자료로 받지 않아 이 답에 표시하지 않아요.'\n"
     "\n\n"
     "def _kst(t):\n"
     "    \"\"\"ISO 시각 → 「2026-11-12 14:05 (한국 시각)」. 읽지 못하면 받은 글자 그대로.\"\"\"\n"
     "    from datetime import datetime, timedelta, timezone\n"
     "    try:\n"
     "        d = datetime.fromisoformat(str(t).replace('Z', '+00:00'))\n"
     "    except ValueError:\n"
     "        return str(t)\n"
     "    if d.tzinfo is None:\n"
     "        return d.strftime('%Y-%m-%d %H:%M')\n"
     "    return d.astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M') + ' (한국 시각)'\n"
     "\n\n"
     "def _prov(e, s):\n"
     "    \"\"\"v0.38 T2-4d: 언제·어떻게 왔나(detail)와 이용 범위(use)를 더한다. 원래 칸은 그대로. 기록이 없는 것은 「기록 없음」으로 — 지어내지 않는다.\"\"\"\n"
     "    e['use'] = USE.get(str(e.get('grade') or '').split(':')[0], '이용 범위 확인 전')\n"
     "    d = []\n"
     "    if s.get('rcept_no'):\n"
     "        e['rcept_no'], e['url'] = s['rcept_no'], s.get('url')\n"
     "        d.append(f\"DART 접수번호 {s['rcept_no']}\")\n"
     "        if s.get('fetched_at'):\n"
     "            d.append(f\"원문을 받은 시각 {_kst(s['fetched_at'])} · {HOW.get(s.get('how'), '받은 방법 기록 없음')}\")\n"

     "    if s.get('collected_at_max'):\n"
     "        d.append(f\"자료를 모은 시각(가장 늦은 줄) {_kst(s['collected_at_max'])}\")\n"
     "    e['detail'] = d\n"
     "    return e\n"
     "\n\n"
     "def _seen_line(info):\n"
     "    \"\"\"J23: 앱이 공시 목록에서 처음 본 시각(자동 확인 기록) 한 줄. 단계 결과가 아니라 답을 보일 때 붙인다.\"\"\"\n"
     "    if not info or not info.get('first_seen_at'):\n"
     "        return '앱이 공시 목록에서 처음 본 시각: 기록 없음(자동 확인 기록이 없는 공시)'\n"
     "    t = f\"앱이 공시 목록에서 처음 본 시각 {_kst(info['first_seen_at'])}\"\n"
     "    if info.get('first_check'):\n"
     "        return t + ' — 관심 종목에 넣은 뒤 첫 확인 때 본 것이라 실제로 공시가 뜬 때보다 늦을 수 있어요'\n"
     "    if info.get('prev_checked_at'):\n"
     "        return t + f\" — 그 직전 확인은 {_kst(info['prev_checked_at'])}, 공시는 그 사이에 목록에 올라왔어요\"\n"
     "    return t\n"
     "\n\n"
     "def _sources(p):\n    out = []\n"),
    ("'index_source', 'segment_source'):\n", "'index_source', 'segment_source', 'filing_source'):\n"),
    ("                    out.append({'what': s.get('origin') or name, 'snapshot': s.get('snapshot'), 'sha256': s.get('sha256'), 'grade': s.get('source_grade'), 'file': s.get('file')})\n",
     "                    out.append(_prov({'what': s.get('origin') or name, 'snapshot': s.get('snapshot'), 'sha256': s.get('sha256'), 'grade': s.get('source_grade'), 'file': s.get('file')}, s))\n"),
    ("        out.append({'what': '사업보고서 원문 색인', 'snapshot': None, 'sha256': (p['doc_source'].get('index') or {}).get('corpusHash'), 'grade': 'official'})\n",
     "        out.append(_prov({'what': '사업보고서 원문 색인', 'snapshot': None, 'sha256': (p['doc_source'].get('index') or {}).get('corpusHash'), 'grade': 'official'}, {}))\n"),
    ("    order = {'estimate': 0, 'fact': 1, 'calc': 2}\n",
     "    order = {'estimate': 0, 'fact': 1, 'calc': 2}\n"
     "    if easy.get('card') == 'filing':                     # v0.38 T2-4d PM 결정 ③: 공시 숫자 화면만 사실 → 계산 → 추정\n"
     "        order = {'fact': 0, 'calc': 1, 'estimate': 2}\n"
     "        items.sort(key=lambda i: order[i['tier']])\n"),
    ("'tables': tables, 'sources': uniq,", "'tables': tables, 'sources': uniq, 'source_notes': [TRADE_STATUS_NOTE],"),
    ("def answer(run, get_packet, name_of=None):\n", "def answer(run, get_packet, name_of=None, seen=None):\n"),
    ("    uniq = []\n    for s in sources:\n        if s not in uniq:\n            uniq.append(s)\n",
     "    uniq = []\n    for s in sources:\n        if s not in uniq:\n            uniq.append(s)\n"
     "    if seen is not None:                                  # v0.38 T2-4d (J23): seen(접수번호) → 앱이 처음 본 기록. 답을 보일 때만 붙임\n"
     "        for s in uniq:\n"
     "            if s.get('rcept_no'):\n"
     "                s['detail'] = list(s.get('detail') or []) + [_seen_line(seen(s['rcept_no']))]\n"),
])
EDITS['mrn/server.py'] = ("seen=lambda no", [
    ("        return answer(run, lambda pid: store.get_packet(pid, o), company_name)\n",
     "        from .autocheck import seen_info                 # v0.38 T2-4d (J23)\n"
     "        return answer(run, lambda pid: store.get_packet(pid, o), company_name, seen=lambda no: seen_info(store, no))\n"),
])
EDITS['mrn/share_api.py'] = ("seen=lambda no", [
    ("        html, meta = share.build(answer(run, get, company_name), receipt(run, get), (q or '')[:120])\n",
     "        from .autocheck import seen_info                 # v0.38 T2-4d (J23)\n"
     "        html, meta = share.build(answer(run, get, company_name, seen=lambda no: seen_info(store, no)), receipt(run, get), (q or '')[:120])\n"),
])
EDITS['mrn/share.py'] = ("source_notes", [
    ("""f'<tr><td>{_e(s.get("what"))}</td>""",
     """f'<tr><td>{_e(s.get("what"))}{"".join("<br><small>" + _e(x) + "</small>" for x in list(s.get("detail") or []) + (["이용 범위: " + s["use"]] if s.get("use") else []))}</td>"""),
    ("nots = [ans.get('not_this')] + list(ans.get('notices') or []) + list(ans.get('limits') or [])",
     "nots = [ans.get('not_this')] + list(ans.get('notices') or []) + list(ans.get('limits') or []) + list(ans.get('source_notes') or [])"),
])
EDITS['web/easy.js'] = ("s.detail", [
    (r"""<p class="hint">이 답에 쓴 자료와 그 자료의 지문(해시)이에요.</p><dl>${a.sources.map(s => `<dt>${esc(grade(s.grade))}</dt><dd>${esc(s.what || '')}<br><span class="mono">""",
     r"""<p class="hint">이 답에 쓴 자료가 언제·어디서·어떻게 왔는지와 그 자료의 지문(해시)이에요.</p><dl>${a.sources.map(s => `<dt>${esc(grade(s.grade))}</dt><dd>${esc(s.what || '')}${(s.detail || []).map(x => `<br><span class="hint">${esc(x)}</span>`).join('')}${s.url ? `<br><a href="${esc(s.url)}" target="_blank" rel="noopener">DART 원문 열기</a>` : ''}${s.use ? `<br><span class="hint">이용 범위: ${esc(s.use)}</span>` : ''}<br><span class="mono">"""),
    (r"""<p class="hint">지문(해시)은 자료 파일이 한 글자라도 바뀌면 달라져요. 같은 지문이면 같은 자료예요.</p>` : ''}""",
     r"""<p class="hint">지문(해시)은 자료 파일이 한 글자라도 바뀌면 달라져요. 같은 지문이면 같은 자료예요.</p>${(a.source_notes || []).map(x => `<p class="hint">${esc(x)}</p>`).join('')}` : ''}"""),
])

todo = {}
for rel, (mark, pairs) in EDITS.items():
    s = (N / rel).read_text(encoding='utf-8')
    if mark in s:
        print(f'{rel}: 이미 적용됨'); continue
    for old, _ in pairs:
        if s.count(old) != 1:
            raise SystemExit(f'{rel}: 「{old[:60]!r}」 자리를 정확히 하나 찾지 못함({s.count(old)}) — 아무것도 바꾸지 않음')
    todo[rel] = (s, pairs)
for rel, (s, pairs) in todo.items():
    for old, new in pairs:
        s = s.replace(old, new)
    (N / rel).write_text(s, encoding='utf-8', newline=''); print(f'{rel}: {len(pairs)}곳 적용')
