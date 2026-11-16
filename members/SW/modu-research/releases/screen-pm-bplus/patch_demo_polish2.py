"""시연 전 작은 흠 정리 2 (PM 2026-11-15): 답 카드 맨 위 값 종류 표시(사실·관계·가정)가 비어 있으면(전문가 모드 흐름 등) 빈 분홍 칩을 그리지 않음.
사용: python patch_demo_polish2.py <화면 폴더> · 되돌리기: before_demo4/research.after_polish1.js · 표식 '시연: 빈 칩 숨김'"""
import sys
from pathlib import Path
p = Path(sys.argv[1]).resolve() / "pages/static/pages/js/pages/research.js"
OLD = '<div class="rs-meta"><span class="chip k-${esc(a.kind)}">${esc(a.kind)}</span>'
NEW = '<div class="rs-meta">${a.kind ? `<span class="chip k-${esc(a.kind)}">${esc(a.kind)}</span>` : \'\'}<!-- 시연: 빈 칩 숨김 -->'
t = p.read_text(encoding="utf-8")
if "시연: 빈 칩 숨김" in t: print("이미 적용"); sys.exit(0)
if t.count(OLD) != 1: sys.exit("바꿀 자리를 못 찾아 아무것도 바꾸지 않았습니다")
p.write_text(t.replace(OLD, NEW), encoding="utf-8", newline="\n"); print("고침: research.js")
