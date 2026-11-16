@echo off
rem 로그인 창 없이 ai-mbc 토큰으로 sw 브랜치 올리기
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0push_with_token.ps1"
