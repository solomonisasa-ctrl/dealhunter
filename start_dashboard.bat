@echo off
cd /d "%~dp0"
start "Deal Hunter Server" cmd /k .venv\Scripts\uvicorn.exe dashboard.server:app --port 8420
timeout /t 3 /nobreak >nul
start "" http://localhost:8420
