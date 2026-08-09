@echo off
cd /d "%~dp0"

REM If the dashboard is already running, just open it. Starting a second
REM server on the same port only fails to bind and leaves a confusing
REM error window instead of opening the app.
curl.exe -s -o NUL --max-time 2 http://localhost:8420/api/health
if %errorlevel%==0 (
    start "" http://localhost:8420
    exit /b
)

echo Starting Deal Hunter...
start "Deal Hunter Server" cmd /k .venv\Scripts\uvicorn.exe dashboard.server:app --port 8420

REM Poll until the server actually accepts connections, rather than
REM guessing with a fixed sleep - a slow start used to open the browser
REM before anything was listening. `ping` is the sleep here rather than
REM `timeout`, which errors out ("input redirection is not supported")
REM when this script runs without an interactive console.
for /l %%i in (1,1,30) do (
    curl.exe -s -o NUL --max-time 1 http://localhost:8420/api/health && goto ready
    ping -n 2 127.0.0.1 >NUL 2>&1
)

echo.
echo Deal Hunter did not start within 30 seconds.
echo Check the "Deal Hunter Server" window for the error.
pause
exit /b

:ready
start "" http://localhost:8420
