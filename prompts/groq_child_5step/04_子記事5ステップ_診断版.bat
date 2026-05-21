@echo off
chcp 65001 > nul
echo ============================================================
echo 子記事作成スクリプト（診断版）
echo ============================================================
echo.
echo Pythonとライブラリの確認中...
echo.

REM Pythonのバージョン確認
"C:\Users\yk6hi\AppData\Local\Programs\Python\Python312\python.exe" --version
if %errorlevel% neq 0 (
    echo ❌ Pythonが見つかりません
    pause
    exit /b 1
)

echo.
echo groqライブラリの確認中...
"C:\Users\yk6hi\AppData\Local\Programs\Python\Python312\python.exe" -c "import groq; print('groq:', groq.__version__)"
if %errorlevel% neq 0 (
    echo.
    echo ❌ groqライブラリがインストールされていません
    echo.
    echo 以下のコマンドを実行してください：
    echo pip install groq --break-system-packages
    echo.
    pause
    exit /b 1
)

echo.
echo requestsライブラリの確認中...
"C:\Users\yk6hi\AppData\Local\Programs\Python\Python312\python.exe" -c "import requests; print('requests:', requests.__version__)"
if %errorlevel% neq 0 (
    echo.
    echo ❌ requestsライブラリがインストールされていません
    echo.
    echo 以下のコマンドを実行してください：
    echo pip install requests --break-system-packages
    echo.
    pause
    exit /b 1
)

echo.
echo ✅ すべての依存関係が確認できました
echo.
echo スクリプトを実行します...
echo.

"C:\Users\yk6hi\AppData\Local\Programs\Python\Python312\python.exe" "G:\マイドライブ\claude-work-shared\prompts\groq_child_5step\auto_post_child_5step.py"

echo.
echo ============================================================
echo 処理完了（エラーがある場合は上記を確認してください）
echo ============================================================
pause
