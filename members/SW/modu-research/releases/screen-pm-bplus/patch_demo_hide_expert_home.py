"""시연용: 숙련자 홈을 화면에서 빼기 (PM 결정 2026-11-13). 사용: python patch_demo_hide_expert_home.py <화면 폴더>
- 숙련자 모드일 때 '홈' = 근거 리서치 (모드 선택·퀴즈·학습 끝·첫 화면 버튼이 모두 근거 리서치로 감)
- 숙련자 모드일 때 왼쪽 메뉴의 '숙련자 홈' 항목을 숨김
- 입문자 모드는 그대로. 숙련자 홈 화면 파일·주소(/home-expert/)는 지우지 않음(되돌리기 쉽게)
- 이미 적용됐으면 건너뜀(표식 '시연: 숙련자 홈 숨김')"""
import sys
from pathlib import Path
ROOT = Path(sys.argv[1]).resolve()
MARK = "시연: 숙련자 홈 숨김"
EDITS = [
    ("pages/static/pages/js/common/core.js",
     "const homeUrl = () => URLS[`home_${getLevel()}`];     // 모드에 맞는 홈 주소\n",
     "// 시연: 숙련자 홈 숨김 (PM 2026-11-13) — 숙련자 홈은 임시 데이터라 시연에서 빼고, 숙련자의 홈은 근거 리서치로\n"
     "const homeUrl = () => getLevel() === 'expert' ? URLS.research : URLS[`home_${getLevel()}`];\n"),
    ("pages/static/pages/js/common/layout.js",
     "  { key: 'expert', icon: 'ti-columns', label: '전문가 모드', href: () => URLS.expert_mode },  // B+ 전문가 모드\n];\n",
     "  { key: 'expert', icon: 'ti-columns', label: '전문가 모드', href: () => URLS.expert_mode },  // B+ 전문가 모드\n"
     "].filter((m) => !(m.key === 'home' && getLevel() === 'expert'));  // 시연: 숙련자 홈 숨김 (PM 2026-11-13)\n"),
]
todo, missing = [], []
for rel, old, new in EDITS:
    t = (ROOT / rel).read_text(encoding="utf-8")
    if MARK in t: print("이미 적용:", rel); continue
    if t.count(old) != 1: missing.append(rel); continue
    todo.append((rel, t.replace(old, new)))
if missing: sys.exit("바꿀 자리를 못 찾아 아무것도 바꾸지 않았습니다: " + ", ".join(missing))
for rel, t in todo:
    (ROOT / rel).write_text(t, encoding="utf-8", newline="\n"); print("고침:", rel)
print("완료")
