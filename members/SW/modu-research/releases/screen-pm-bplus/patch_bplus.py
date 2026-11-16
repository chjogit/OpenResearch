"""B+ 전문가 모드 패치 (PM 2026-11-13). 사용: python patch_bplus.py <화면 폴더(manage.py 있는 곳)>
- 바꿀 자리를 모두 먼저 확인하고, 하나라도 없으면 아무것도 바꾸지 않는다.
- 이미 적용됐으면(표식 'B+ 전문가 모드') 건너뛴다(여러 번 돌려도 같음).
- 새 파일 3개(new/pages/…)는 그대로 복사한다."""
import shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(sys.argv[1]).resolve()
MARK = "B+ 전문가 모드"

EDITS = [
    ("stocknote/urls.py",
     '    path("api/<path:sub>", engine_proxy.forward),   # 근거 리서치 화면 → 모두의리서치 엔진 전달\n',
     '    path("api/<path:sub>", engine_proxy.forward),   # 근거 리서치 화면 → 모두의리서치 엔진 전달\n'
     '    path("engine/expert", engine_proxy.expert_page),             # B+ 전문가 모드: 엔진 전문가 화면(iframe 속)\n'
     '    path("engine-static/<str:name>", engine_proxy.engine_static),  # B+ 전문가 모드: 그 화면의 css·js\n'),
    ("pages/urls.py",
     '    path("research/", views.research, name="research"),   # 근거 리서치 (엔진 연결, 주소 # 뒤로 화면 전환)\n',
     '    path("research/", views.research, name="research"),   # 근거 리서치 (엔진 연결, 주소 # 뒤로 화면 전환)\n'
     '    path("expert-mode/", views.expert_mode, name="expert_mode"),  # B+ 전문가 모드 (엔진 전문가 화면을 이 틀 안에)\n'),
    ("pages/templates/pages/base.html",
     '      research: "{% url \'pages:research\' %}",\n',
     '      research: "{% url \'pages:research\' %}",\n'
     '      expert_mode: "{% url \'pages:expert_mode\' %}",  {# B+ 전문가 모드 #}\n'),
    ("pages/static/pages/js/common/layout.js",
     "  { key: 'research', icon: 'ti-file-search', label: '근거 리서치', href: () => URLS.research },\n",
     "  { key: 'research', icon: 'ti-file-search', label: '근거 리서치', href: () => URLS.research },\n"
     "  { key: 'expert', icon: 'ti-columns', label: '전문가 모드', href: () => URLS.expert_mode },  // B+ 전문가 모드\n"),
]
APPENDS = [
    ("pages/views.py",
     '\n\n# B+ 전문가 모드 (PM 추가 2026-11-13): 엔진 전문가 화면을 이 화면 틀 안에 보인다\n'
     'def expert_mode(request):\n    return render(request, "pages/expert-mode.html")\n'),
    ("pages/engine_proxy.py", (HERE / "new/proxy_append.py.txt").read_text(encoding="utf-8")),
]
NEW = ["pages/templates/pages/expert-mode.html",
       "pages/static/pages/css/pages/expert-mode.css",
       "pages/static/pages/css/pages/expert-skin.css"]

def main():
    if not (ROOT / "manage.py").exists():
        sys.exit(f"manage.py 가 없습니다: {ROOT}")
    todo, missing = [], []
    for rel, old, new in EDITS:
        t = (ROOT / rel).read_text(encoding="utf-8")
        if MARK in t: print("이미 적용:", rel); continue
        if t.count(old) != 1: missing.append(rel); continue
        todo.append((rel, t.replace(old, new)))
    for rel, add in APPENDS:
        t = (ROOT / rel).read_text(encoding="utf-8")
        if MARK in t: print("이미 적용:", rel); continue
        todo.append((rel, t.rstrip("\n") + "\n" + add))
    if missing:
        sys.exit("바꿀 자리를 못 찾아 아무것도 바꾸지 않았습니다: " + ", ".join(missing))
    for rel, t in todo:
        (ROOT / rel).write_text(t, encoding="utf-8", newline="\n"); print("고침:", rel)
    for rel in NEW:
        shutil.copyfile(HERE / "new" / rel, ROOT / rel); print("새 파일:", rel)
    print("완료")

main()
