# v0.28 되돌리기
1. stop.cmd
2. before\mrn\server.py, before\mrn\nodes.py → modu-research-nodes\mrn\ , before\web\easy.js → modu-research-nodes\web\ 로 복사(덮어쓰기)
   (주의: 이 뒤에 다른 버전이 같은 파일을 바꿨다면 통째 덮지 말고 patch-kit의 덧붙인 줄만 빼기)
3. 새 파일 mrn\attention.py, mrn\attention_api.py, tests\test_attention.py 는 남아 있어도 서버가 부르지 않음
4. start.cmd → 「사람들이 얼마나 몰렸나?」 카드가 없어지면 완료
