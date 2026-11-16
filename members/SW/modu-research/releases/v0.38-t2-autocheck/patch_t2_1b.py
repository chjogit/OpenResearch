"""v0.38 T2-1b 재검토(다른 시각) 반영 — dartdocs(F5: DART가 JSON이 아닌 응답) · 화면(F4: 최근 14일·「새로」 표시·처음 본 시각 범위).
autocheck.py 는 new/ 의 파일로 바꾼다(F1·F2·F3·F6·F7). 여러 번 돌려도 같은 결과."""
import sys
from pathlib import Path

N = Path(sys.argv[1])


def patch(rel, old, new, mark):
    p = N / rel; s = p.read_text(encoding='utf-8')
    if mark in s:
        print(f'{rel}: 이미 적용됨'); return
    if s.count(old) != 1:
        raise SystemExit(f'{rel}: 바꿀 자리를 정확히 하나 찾지 못함({s.count(old)})')
    p.write_text(s.replace(old, new), encoding='utf-8', newline='')
    print(f'{rel}: 적용')


BAD = "'DART 응답을 읽지 못했어요(점검 중이거나 일시 오류일 수 있어요).'"
patch('mrn/dartdocs.py',
      "        d = json.loads(get(f'{LIST_API}?{q}').decode('utf-8'))\n",
      "        b = get(f'{LIST_API}?{q}')\n"
      "        try:                                                  # v0.38 T2-1b(F5): 점검 화면 등 JSON이 아닌 응답은 「응답을 읽지 못함」으로 멈춤 사유에 넣음(해석만 감쌈 — 다른 오류는 가리지 않음)\n"
      "            d = json.loads(b.decode('utf-8'))\n"
      "        except (ValueError, UnicodeDecodeError):\n"
      f"            raise DartDocsError('dart_bad_response', {BAD}) from None\n"
      "        if not isinstance(d, dict):\n"
      f"            raise DartDocsError('dart_bad_response', {BAD})\n",
      "T2-1b(F5)")
patch('mrn/dartdocs.py',
      "        if page >= int(d.get('total_page') or 1):\n",
      "        try:\n"
      "            last = int(d.get('total_page') or 1)\n"
      "        except (TypeError, ValueError):\n"
      f"            raise DartDocsError('dart_bad_response', {BAD}) from None\n"
      "        if page >= last:\n",
      "last = int(d.get('total_page') or 1)")

patch('web/easy.html',
      '<h3>새로 나온 공시 <span class="hint">(자동 확인)</span></h3>',
      '<h3>관심 종목 공시 <span class="hint">(최근 14일 · 자동 확인)</span></h3>',
      '(최근 14일 · 자동 확인)')
patch('web/watch.js',
      "  const tag = x.first_check ? ' <span class=\"hint\">(등록 때 본 공시)</span>' : '';",
      "  const tag = (x.first_check ? ' <span class=\"hint\">(등록 때 본 공시)</span>' : '') + (x.is_new ? ' <span class=\"b calc\">새로</span>' : '');   // T2-1b F4",
      'T2-1b F4')
patch('web/watch.js',
      "  return `<tr><td>${esc(x.rcept_dt)}</td><td>${esc(x.name || x.ticker)}</td><td>${esc(x.label)}${fix}</td>",
      "  return `<tr><td title=\"${esc(wSeen(x))}\">${esc(x.rcept_dt)}</td><td>${esc(x.name || x.ticker)}</td><td>${esc(x.label)}${fix}</td>",
      'title="${esc(wSeen(x))}">${esc(x.rcept_dt)}</td><td>${esc(x.name')
patch('web/watch.js',
      "function wSub(x){",
      "function wSeen(x){   // T2-1b F2: 앱이 처음 본 시각과, 실제 공시가 뜬 때의 범위\n"
      "  return `앱이 처음 본 시각 ${kst(x.first_seen_at)}` + (x.seen_gap_min != null ? ` · 실제 공시는 그 전 ${x.seen_gap_min}분 안` : x.first_check ? ' · 처음 등록 때 본 공시' : '');\n"
      "}\n"
      "function wSub(x){",
      'function wSeen(')
patch('web/watch.js',
      "  return `<tr><td>${esc(x.rcept_dt)}</td><td>${esc(x.filer || '')}</td>",
      "  return `<tr><td title=\"${esc(wSeen(x))}\">${esc(x.rcept_dt)}${x.is_new ? ' <span class=\"b calc\">새로</span>' : ''}</td><td>${esc(x.filer || '')}</td>",
      "${esc(x.rcept_dt)}${x.is_new")
patch('web/watch.js',
      "      + sec(`중 · ${a.tier_note['중']}`, '3등급', b['중'], true) + sec(`하 · ${a.tier_note['하']}`, '3등급 · 접어 둠', b['하'], false)\n"
      "      : '<p class=\"hint\">관심 종목의 새 공시가 아직 없어요.</p>'}",
      "      + sec(`중 · ${a.tier_note['중']}`, '3등급', b['중'], true) + sec(`하 · ${a.tier_note['하']}`, '3등급 · 접어 둠', b['하'], false)\n"
      "      + (b['하_more'] ? `<p class=\"hint\">참고 공시 ${b['하_more']}줄은 더 있어요(오래된 것부터 생략).</p>` : '')\n"
      "      : `<p class=\"hint\">관심 종목의 최근 ${a.window_days || 14}일 공시가 아직 없어요.</p>`}",
      "b['하_more']")
