# 되돌리기 (v0.35 → v0.34)
1. stop.cmd
2. 아래 두 파일을 before 폴더 것으로 덮어쓰기
   - before\mrn\server.py  → modu-research-nodes\mrn\server.py
   - before\web\index.html → modu-research-nodes\web\index.html
3. modu-research-nodes\tests\test_v035_tp_ticker.py 를 다른 곳으로 옮기기(되돌린 서버에서는 실패함)
   web\tp_timeline.js 는 index.html이 더 이상 부르지 않으므로 남겨 둬도 무해
4. start.cmd → Ctrl+F5
확인: SHA256SUMS 의 before 해시와 같아야 함.
