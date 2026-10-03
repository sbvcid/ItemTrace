@echo off
REM 啟動 ItemTrace：安裝依賴 → 初始化資料庫 → 開 HTTP 服務
REM 這支腳本只是把 README 的三步包起來，沒有任何額外邏輯。

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [錯誤] 找不到 python。請先安裝 Python 3.11 以上，並勾選 Add Python to PATH。
    pause
    exit /b 1
)

echo [1/3] 安裝依賴...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
    echo [錯誤] 依賴安裝失敗。可以手動執行：pip install -r requirements.txt
    pause
    exit /b 1
)

echo [2/3] 初始化資料庫（已存在會直接跳過）...
python shopctl.py init
if errorlevel 1 (
    echo [錯誤] 初始化失敗。
    pause
    exit /b 1
)

echo [3/3] 啟動服務。要讓手機連進來，請把 config.json 的 server_host 改成 0.0.0.0。
echo       然後在同一個 Wi-Fi 用瀏覽器打 http://^<電腦IP^>:8731/
python serve.py

pause
