# 되돌리기 (v0.24 → v0.23.3)
1. stop.cmd
2. (넣었다면) .venv\Scripts\python.exe -X utf8 -m mrn.broker_quarter revert  — 자동 승인분 삭제. 새 표 자체는 남아도 이전 버전은 읽지 않음.
3. before\ 의 README.md, mrn\ 4개, web\ 5개를 앱 폴더 같은 자리에 덮어쓰기
4. 새 파일(mrn\broker_quarter.py, tests\test_broker_quarter.py, apply-quarter.cmd)은 지우거나 _to_delete 로 옮기기
5. before\SHA256SUMS-before.txt 확인 → start.cmd
