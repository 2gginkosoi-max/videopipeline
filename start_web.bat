@echo off
chcp 65001 >nul
title ГУСЬ ПЕРЕВОДИЛА - веб-конвейер
echo.
echo   Запуск веб-интерфейса конвейера...
echo   http://127.0.0.1:8000
echo.
start "" http://127.0.0.1:8000
"D:\AI\python310\python.exe" "D:\AI\VIDEO_PIPELINE\web\app.py"
pause
