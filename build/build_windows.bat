@echo off
setlocal

cd /d "%~dp0\.."

echo ============================================================
echo TikTok Video Performance - Windows Build
echo ============================================================

echo [1/5] Checking Python...
python --version || goto :error

echo [2/5] Installing/updating PyInstaller...
python -m pip install --upgrade pyinstaller || goto :error

echo [3/5] Syntax check...
python -m py_compile gui_app.py || goto :error
python -m py_compile run_batch.py || goto :error
python -m py_compile app\session_manager.py || goto :error
python -m py_compile app\tiktok_login.py || goto :error
python -m py_compile app\collectors\tiktok_batch.py || goto :error
python -m py_compile app\collectors\tiktok_profile_batch.py || goto :error
python -m py_compile app\collectors\tiktok_profile_http.py || goto :error
python -m py_compile app\utils\profile_excel.py || goto :error

echo [4/5] Building...
python -m PyInstaller --clean --noconfirm TikTokVideoPerformance.windows.spec || goto :error

echo [5/5] Done.
echo.
echo BUILD THANH CONG
echo %CD%\dist\TikTok Video Performance\TikTok Video Performance.exe
echo.
pause
exit /b 0

:error
echo.
echo BUILD THAT BAI
pause
exit /b 1
