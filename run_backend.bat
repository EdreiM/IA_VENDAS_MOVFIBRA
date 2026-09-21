@echo off
cd /d "%~dp0backend"
set PYTHONPATH=%CD%
"..\\.venv\\Scripts\\python.exe" -m uvicorn app.main:app --reload --port 8001
