@echo off
cd /d "%~dp0"
where uv >nul 2>nul || (echo uv is required: https://docs.astral.sh/uv/ & exit /b 1)
where node >nul 2>nul || (echo Node.js is required for the official-source verifier & exit /b 1)
if not exist .venv\Scripts\python.exe uv --cache-dir .uv-cache venv --python 3.12 .venv
uv --cache-dir .uv-cache pip install --python .venv/Scripts/python.exe fastapi==0.115.12 uvicorn==0.34.2 pydantic==2.11.7 pymupdf numpy
echo Setup done. Run start.cmd
