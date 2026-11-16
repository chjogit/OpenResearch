"""v0.38 T2-2 화면 다듬기 2(재점검, 휴대폰 380px): 표를 줄 카드로 쌓고, 묶음 기간은 같은 해면 「2026-11-05~11-12」로 줄인다. 여러 번 돌려도 같은 결과."""
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
      "  return `<tr class=\"wgrp\"><td>${esc(x.from)}~${esc(x.to)}</td>",
      "  const span = x.from.slice(0, 4) === x.to.slice(0, 4) ? `${x.from}~${x.to.slice(5)}` : `${x.from}~${x.to}`;   // T2-2c 같은 해면 짧게\n"
      "  return `<tr class=\"wgrp\"><td>${esc(span)}</td>",
      'T2-2c 같은 해면')
patch('web/easy.css',
      ".wsub td:nth-child(2){white-space:normal;min-width:4em}   /* T2-2b 회사 이름 한 자씩 꺾임 방지 */",
      ".wsub td:nth-child(2){white-space:normal;min-width:4em}   /* T2-2b 회사 이름 한 자씩 꺾임 방지 */\n"
      "@media (max-width:520px){   /* T2-2c 휴대폰: 표를 줄 카드로 쌓음(가로 스크롤 없이 읽기) */\n"
      "  #wNew .wscroll{max-height:none;border:none}\n"
      "  #wNew table,#wNew tbody,#wNew tr,#wNew td{display:block;width:auto}\n"
      "  #wNew th{display:none}\n"
      "  #wNew tr{border-bottom:1px solid var(--line);padding:6px 0}\n"
      "  #wNew td{padding:1px 4px;white-space:normal!important;border:none}\n"
      "  #wNew td:first-child{color:var(--mute);font-size:13px}\n"
      "  .wgrp details table{margin:4px 0 0 8px}\n"
      "}",
      'T2-2c 휴대폰')
