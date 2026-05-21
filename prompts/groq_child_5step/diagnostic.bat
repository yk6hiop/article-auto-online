@echo off
echo ============================================================
echo Child Article Script - Diagnostic Version
echo ============================================================
echo.
echo Checking Python...
echo.

"C:\Users\yk6hi\AppData\Local\Programs\Python\Python312\python.exe" --version
if %errorlevel% neq 0 (
    echo ERROR: Python not found
    pause
    exit /b 1
)

echo.
echo Checking groq library...
"C:\Users\yk6hi\AppData\Local\Programs\Python\Python312\python.exe" -c "import groq; print('groq version:', groq.__version__)"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: groq library is not installed
    echo.
    echo Please run this command:
    echo pip install groq --break-system-packages
    echo.
    pause
    exit /b 1
)

echo.
echo Checking requests library...
"C:\Users\yk6hi\AppData\Local\Programs\Python\Python312\python.exe" -c "import requests; print('requests version:', requests.__version__)"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: requests library is not installed
    echo.
    echo Please run this command:
    echo pip install requests --break-system-packages
    echo.
    pause
    exit /b 1
)

echo.
echo OK: All dependencies found
echo.
echo Running script...
echo.

"C:\Users\yk6hi\AppData\Local\Programs\Python\Python312\python.exe" "G:\マイドライブ\claude-work-shared\prompts\groq_child_5step\auto_post_child_5step.py"

echo.
echo ============================================================
echo Done
echo ============================================================
pause
