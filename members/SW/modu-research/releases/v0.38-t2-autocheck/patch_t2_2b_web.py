"""v0.38 T2-2 화면 다듬기(재점검): 묶음을 펼쳤을 때 안쪽 표는 접수일·보고자·보고서만 — 회사·종류를 줄마다 되풀이하지 않는다(중간 폭에서 글자가 한 자씩 꺾이던 문제). 여러 번 돌려도 같은 결과."""
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


patch('web/watch.js',
      "    <table class=\"jt\">${x.rows.map(wRow).join('')}</table></details></td></tr>`;",
      "    <table class=\"jt wsub\"><tr><th>접수일</th><th>보고자</th><th>보고서</th></tr>${x.rows.map(wSub).join('')}</table></details></td></tr>`;   // T2-2b wSub",
      'T2-2b wSub')
patch('web/watch.js',
      "function wItem(x){",
      "function wSub(x){   // 묶음 안쪽 줄: 회사·종류는 묶음 머리에 있으므로 되풀이하지 않음\n"
      "  return `<tr><td>${esc(x.rcept_dt)}</td><td>${esc(x.filer || '')}</td><td><a href=\"${esc(x.url)}\" target=\"_blank\" rel=\"noopener\">${esc(x.report_nm)}</a>${x.corrected ? ' <span class=\"b estimate\">정정</span>' : ''}${x.first_check ? ' <span class=\"hint\">(등록 때 본 공시)</span>' : ''}</td></tr>`;\n"
      "}\n"
      "function wItem(x){",
      'function wSub(')
patch('web/easy.css',
      "#wNew td:first-child,#wNew th:first-child{white-space:nowrap}",
      "#wNew td:first-child,#wNew th:first-child{white-space:nowrap}\n"
      "#wNew td:nth-child(2){white-space:nowrap}.wsub td:nth-child(2){white-space:normal;min-width:4em}   /* T2-2b 회사 이름 한 자씩 꺾임 방지 */",
      'T2-2b 회사 이름')
