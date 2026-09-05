@echo off
rem Avvia AI Video Maker: backend :8000 + frontend :3000, poi apre il browser.
setlocal
cd /d %~dp0

if not exist backend\.venv\Scripts\python.exe (
  echo Venv mancante: esegui prima setup.bat
  exit /b 1
)

echo [1/3] Backend su http://127.0.0.1:8000 ...
start "AI Video Maker - Backend" /min /d "%~dp0backend" "%~dp0backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

set /a tries=0
:wait_backend
rem attesa 1s senza stdin (timeout.exe richiede una console)
ping -n 2 127.0.0.1 >nul
set /a tries+=1
curl.exe -sf http://127.0.0.1:8000/api/health >nul 2>&1
if not errorlevel 1 goto backend_ok
if %tries% GEQ 60 (
  echo Backend non partito entro 60s. Controlla la finestra "AI Video Maker - Backend".
  exit /b 1
)
goto wait_backend
:backend_ok
echo Backend OK.

echo [2/3] Frontend su http://localhost:3000 ...
if not exist frontend\.next (
  echo Build produzione mancante, la creo...
  cd frontend
  call npm run build
  if errorlevel 1 ( echo next build fallito. & exit /b 1 )
  cd /d %~dp0
)
start "AI Video Maker - Frontend" /min /d "%~dp0frontend" npm run start -- -p 3000

echo [3/3] Apro il browser...
ping -n 4 127.0.0.1 >nul
if /i "%1"=="--no-browser" goto done
start http://localhost:3000
:done
echo Fatto. Ferma tutto con ferma.bat.
