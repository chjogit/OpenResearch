@echo off
cd /d "%~dp0"
rem v0.24: 증권사 보고서의 분기 전망과 순이익 전망을 새 표(broker_forecasts_v2)에 넣습니다. 기존 전망 표는 건드리지 않습니다.
rem 먼저 stop.cmd 로 앱을 끈 뒤 실행하세요. 끝나면 start.cmd.
rem 되돌리기: .venv\Scripts\python.exe -X utf8 -m mrn.broker_quarter revert
.venv\Scripts\python.exe -X utf8 -m mrn.broker_quarter apply
pause
