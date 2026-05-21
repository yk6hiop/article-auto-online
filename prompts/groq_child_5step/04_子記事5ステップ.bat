@echo off
chcp 65001 > nul
echo ============================================================
echo 子記事作成スクリプト（Groq 5ステップ + WordPress投稿版）
echo ============================================================
echo.
echo 【処理内容】
echo Step1: 構成案生成 (5秒)
echo Step2: 本文執筆 (5秒)
echo Step3: 品質チェック+修正 (10秒)
echo Step4: 引き算処理 (5秒)
echo Step5: WordPress投稿 (3秒)
echo 合計: 約28秒
echo.
echo Googleドライブから実行します...
echo.
"C:\Users\yk6hi\AppData\Local\Programs\Python\Python312\python.exe" "G:\マイドライブ\claude-work-shared\prompts\groq_child_5step\auto_post_child_5step.py"
echo.
echo ============================================================
echo 処理完了
echo ============================================================
pause
