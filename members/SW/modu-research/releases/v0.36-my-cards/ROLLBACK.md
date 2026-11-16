# 되돌리기 (v0.36 → v0.35)
1. stop.cmd
2. before 폴더 것으로 덮어쓰기: before\mrn\server.py, before\mrn\easy.py → modu-research-nodes\mrn\ / before\web\index.html → modu-research-nodes\web\
3. modu-research-nodes\tests\test_v036_mycards.py 를 다른 곳으로 옮기기(되돌린 앱에서는 실패함)
   mrn\mycards.py, web\mycards.js 는 아무도 부르지 않게 되므로 남겨 둬도 무해
4. start.cmd → Ctrl+F5
- data\nodes.sqlite 의 my_cards 표는 남지만 v0.35 앱은 읽지 않음(다른 표에 영향 없음).
확인: SHA256SUMS 의 before 해시와 같아야 함.
