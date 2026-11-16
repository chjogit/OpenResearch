# v0.2-stable 되돌리기 안내

보관 시점: 에이전트 작업 시작 직전 (증권사 전망·예시 사례·내 유형까지 포함된 상태)
- app.tgz: 앱 전체(가상환경·데이터 제외)
- nodes.sqlite: 데이터베이스(승인 기록·워크플로·실행 기록)
- manifest.csv / manifest.json: 증권사 보고서 목록(파일명에 증권사명 추가된 상태)
- SHA256SUMS.txt: 위 파일들의 해시

## 되돌리는 법 (기존 폴더를 지우지 않는 방식)
1. 지금 앱 끄기: modu-research-nodes\stop.cmd
2. 이 폴더의 restore.cmd 더블클릭
   → ..\..\modu-research-nodes-v0.2-stable 폴더가 새로 만들어지고 앱과 DB가 복원됩니다.
3. 새 폴더에서 setup.cmd → start.cmd
4. 문제없으면 그 폴더를 계속 쓰거나, 원래 폴더 이름과 바꾸면 됩니다.
