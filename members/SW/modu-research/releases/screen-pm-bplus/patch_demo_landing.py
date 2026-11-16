"""시연: 첫 화면(랜딩) 검색칸도 근거 리서치로 (PM 2026-11-15). 첫 화면 템플릿은 주소를 직접 적어 두어 URLS.chat 바꾸기가 닿지 않았음.
사용: python patch_demo_landing.py <화면 폴더> · 되돌리기: before_demo4/index.html · 표식 '시연: 첫 화면 검색 → 근거 리서치'"""
import sys
from pathlib import Path
p = Path(sys.argv[1]).resolve() / "pages/templates/pages/index.html"
OLD = ("    <h2>궁금한 종목이나 용어를 물어보세요</h2>\n"
       "    <form action=\"{% url 'pages:chat' %}\" role=\"search\">\n"
       "      <input name=\"q\" placeholder=\"예: ETF 총보수가 뭐야?\" aria-label=\"AI에게 질문하기\">\n")
NEW = ("    <h2>궁금한 회사나 질문을 근거로 찾아보세요</h2>  {# 시연: 첫 화면 검색 → 근거 리서치 (PM 2026-11-15) #}\n"
       "    <form action=\"{% url 'pages:research' %}\" role=\"search\">\n"
       "      <input name=\"q\" placeholder=\"예: 삼성전자 영업이익과 현금흐름은?\" aria-label=\"근거 리서치에서 찾기\">\n")
t = p.read_text(encoding="utf-8")
if "시연: 첫 화면 검색 → 근거 리서치" in t: print("이미 적용"); sys.exit(0)
if t.count(OLD) != 1: sys.exit("바꿀 자리를 못 찾아 아무것도 바꾸지 않았습니다")
p.write_text(t.replace(OLD, NEW), encoding="utf-8", newline="\n"); print("고침: index.html")
