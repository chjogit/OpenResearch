"""시연 전 작은 흠 정리 (PM 2026-11-15). 사용: python patch_demo_polish.py <화면 폴더>
1) 답 카드·근거 서랍의 「기준 날짜」: 엔진이 준 원문(예: 2026-11-15T02:58:52.069280+00:00, 세계 표준시)을 한국 시각으로
   - 「…T16:00:00+09:00」(장 마감 기준) → 「2026-11-14 장 마감(16:00)」
   - 그 밖의 시각 → 「2026-11-15 11:58 (한국 시각)」 · 날짜만 → 그대로 · 비어 있으면 「지금」
2) 답 카드 제목: 회사 이름이 없을 때(전문가 모드에서 여러 회사를 섞은 흐름 등) 앞의 「 · 」를 빼기
3) 왼쪽 메뉴 아래 「화면의 수치는 임시 데이터입니다.」: 실제 엔진으로 도는 근거 리서치·전문가 모드에서는 숨김(다른 화면은 그대로)
이미 적용됐으면 건너뜀(표식 '시연: 작은 흠 정리')"""
import sys
from pathlib import Path
ROOT = Path(sys.argv[1]).resolve()
MARK = "시연: 작은 흠 정리"
JS = "pages/static/pages/js/"
FMT = r'''/* 시연: 작은 흠 정리 (PM 2026-11-15) — 기준 날짜를 한국 시각으로 */
function fmtCut(v) {
  if (!v) return '지금';
  const s = String(v);
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  if (/T16:00:00(\.0+)?\+09:00$/.test(s)) return `${s.slice(0, 10)} 장 마감(16:00)`;
  const d = new Date(s); if (isNaN(d)) return s;
  const k = new Date(d.getTime() + 9 * 3600 * 1000).toISOString();   // 한국 시각 = 세계 표준시 + 9시간
  return `${k.slice(0, 10)} ${k.slice(11, 16)} (한국 시각)`;
}
'''
EDITS = [
    (JS + "pages/research.js", "const cardName = (id, t, s) =>", FMT + "const cardName = (id, t, s) =>"),
    (JS + "pages/research.js",
     "<b class=\"rs-date\">${esc(a.cutoff || '지금')}</b>",
     "<b class=\"rs-date\">${esc(fmtCut(a.cutoff))}</b>", 2),   # 답 카드 머리 + 나란히 보기
    (JS + "pages/research.js",
     "<dt>기준 날짜</dt><dd class=\"rs-date\">${esc(a.cutoff || '지금')}</dd>",
     "<dt>기준 날짜</dt><dd class=\"rs-date\">${esc(fmtCut(a.cutoff))}</dd>"),
    (JS + "pages/research.js",
     "<h2 class=\"rs-headline\">${esc(a.name)} · ${esc(cardName(a.card, a.card_title))}</h2>",
     "<h2 class=\"rs-headline\">${a.name ? `${esc(a.name)} · ` : ''}${esc(cardName(a.card, a.card_title))}</h2>"),
    (JS + "common/layout.js",
     '    <p class="side-note hide-closed">화면의 수치는 임시 데이터입니다.</p>',
     "    ${['research', 'expert'].includes(page) ? '' : '<p class=\"side-note hide-closed\">화면의 수치는 임시 데이터입니다.</p>'}  <!-- 시연: 작은 흠 정리 — 실제 엔진 화면에서는 숨김 -->"),
]
texts, miss = {}, []
for e in EDITS:
    rel, old, new = e[:3]; want = e[3] if len(e) > 3 else 1
    cur = texts.get(rel) or (ROOT / rel).read_text(encoding="utf-8")
    if MARK in (ROOT / rel).read_text(encoding="utf-8"):
        print("이미 적용:", rel); continue
    if cur.count(old) != want: miss.append(f"{rel}: {old[:40]}"); continue
    texts[rel] = cur.replace(old, new)
if miss: sys.exit("바꿀 자리를 못 찾아 아무것도 바꾸지 않았습니다:\n  " + "\n  ".join(miss))
for rel, t in texts.items():
    (ROOT / rel).write_text(t, encoding="utf-8", newline="\n"); print("고침:", rel)
print("완료")
