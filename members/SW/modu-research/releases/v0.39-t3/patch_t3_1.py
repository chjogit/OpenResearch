"""v0.39 T3-1 관심회사 주가 큰 움직임 감지(새 파일 mrn/surge.py)를 앱 일정·자동 확인 상태·관심회사 공시함 화면에 잇는다. 더하기만.
고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
WSURGE = r'''function wSurge(s){   // v0.39 T3-1 주가 큰 움직임 — 이유는 판단하지 않고 같은 날 공시만 보임
  if (!s) return '';
  const st = !s.has_key ? 'KIS 키가 없어 주가 움직임 감지는 쉬고 있어요(local-env.cmd 의 KIS_APP_KEY·KIS_APP_SECRET).'
    : !s.enabled ? '주가 움직임 감지가 꺼져 있어요(MODU_SURGE=0).'
    : `장중 ${s.minutes}분마다 확인 · 오늘 바로 확인 ${s.checks_today}/${s.daily_cap}번 · KIS 조회 ${s.kis_calls_today}회` + (s.last_poll ? ` · 마지막 ${kst(s.last_poll.at)} — ${s.last_poll.message || ''}` : '');
  const pct = v => v == null ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(2)}%`;
  const ev = s.events || [];
  const rows = ev.map(e => `<tr><td>${esc(e.day)}</td><td>${esc(e.name || e.ticker)}</td><td class="n">${pct(e.pct)}</td><td class="n">${e.mkt_pct == null ? '—' : esc(e.mkt) + ' ' + pct(e.mkt_pct)}</td>
    <td>${e.filings.length ? e.filings.map(f => `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.report_nm)}</a>`).join('<br>') : '<span class="hint">같은 날 공시 없음</span>'}</td></tr>`).join('');
  return `<details class="wsec" open><summary><b>주가가 크게 움직인 관심회사</b> <span class="hint">최근 14일 · ${ev.length}건</span></summary>
    <p class="hint">${esc(st)}</p>
    ${rows ? `<div class="wscroll"><table class="jt"><tr><th>거래일</th><th>회사</th><th>전일 대비</th><th>같은 시장 지수</th><th>같은 날 공시</th></tr>${rows}</table></div>` : '<p class="hint">최근 14일에 크게 움직인 관심회사가 없어요.</p>'}
    <p class="hint">${esc(s.note || '')}</p></details>`;
}
'''
EDITS = {
    'mrn/autocheck.py': ("def _surge(", [
        ("    s = Scheduler(store, env)\n    SCHED['scheduler'] = s\n    return s.start()\n",
         "    s = Scheduler(store, env)\n    SCHED['scheduler'] = s\n    ok = s.start()\n"
         "    try:                                                         # v0.39 T3-1 주가 큰 움직임 감지(MODU_SURGE=0 이면 끔)\n"
         "        from . import surge as S\n"
         "        S.start(store, env)\n"
         "    except Exception:                                            # 감지가 못 켜져도 공시 확인 일정은 그대로\n"
         "        pass\n"
         "    return ok\n"),
        ("\n\ndef status(store, tickers, env=None):\n",
         "\n\ndef _surge(store, tickers, env=None):\n"
         "    \"\"\"v0.39 T3-1: 주가 큰 움직임 상태. 실패해도 공시함 상태는 그대로 나가게 None.\"\"\"\n"
         "    try:\n"
         "        from . import surge as S\n"
         "        return S.status(store, tickers, env)\n"
         "    except Exception:\n"
         "        return None\n"
         "\n\ndef status(store, tickers, env=None):\n"),
        ("            'tier_note': G.TIER_NOTE, 'grade_label': G.GRADE_LABEL,\n",
         "            'tier_note': G.TIER_NOTE, 'grade_label': G.GRADE_LABEL,\n            'surge': _surge(store, tickers, env),               # v0.39 T3-1\n"),
    ]),
    'web/watch.js': ("function wSurge", [
        ("function wItem(x){\n", WSURGE + "function wItem(x){\n"),
        ("      <button id=\"wCheck\" class=\"ghost\">지금 확인</button></div>\n    ${any ? sec(",
         "      <button id=\"wCheck\" class=\"ghost\">지금 확인</button></div>\n    ${wSurge(a.surge)}\n    ${any ? sec("),
    ]),
}
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
