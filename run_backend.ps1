# Sobe a API Sofia (requer PostgreSQL + DATABASE_URL no .env da raiz)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $root "backend")
$env:PYTHONPATH = (Get-Location).Path
& (Join-Path $root ".venv\Scripts\python.exe") -m pip install -q -r requirements.txt
& (Join-Path $root ".venv\Scripts\python.exe") -m uvicorn app.main:app --reload --port 8001
