@echo off
title 杖劍傳說助手
color 3f

rem 切換到腳本所在目錄，這樣從哪裡點都能正確找到 config 與 templates
cd /d "%~dp0"

rem ===== 可調參數 =====
rem 留空表示照 config.yaml 的設定跑。
rem 常用寫法：
rem   set "ARGS=-n 5"          完成 5 次就停
rem   set "ARGS=--once"        只跑一輪，忽略每日排程
rem   set "ARGS=--dry-run"     只判斷不點擊，安全驗證流程
set "ARGS="

set "ENTRY=main.py"
set "EXE=dist\杖劍傳說助手.exe"

echo [資訊] 杖劍傳說助手
echo.

rem 已經打包過就直接跑 EXE，否則走 Python
if exist "%EXE%" (
    echo [資訊] 使用打包版本：%EXE%
    rem 注意：--windowed 打包的執行檔屬於 GUI 子系統，cmd 直接呼叫不會等它
    rem       結束就往下跑。start /wait 才能讓這個視窗陪著它到收工。
    start /wait "" "%EXE%" run %ARGS%
    goto :done
)

if not exist "%ENTRY%" (
    echo [錯誤] 找不到主程式：%ENTRY%
    goto :error
)

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [錯誤] 找不到 python，請先安裝 Python 3.14 並加入 PATH
    goto :error
)

rem 檢查相依套件，缺了就提示安裝
python -c "import cv2, numpy, yaml" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [警告] 相依套件不完整，正在安裝 ...
    python -m pip install -r requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo [錯誤] 套件安裝失敗
        goto :error
    )
)

echo [資訊] 開始執行 ... 按 Ctrl+C 可隨時停止
echo.
python "%ENTRY%" run %ARGS%

:done
if %ERRORLEVEL% neq 0 (
    echo.
    echo [錯誤] 執行結束，回傳碼 %ERRORLEVEL%
    goto :error
)

echo.
echo [狀態] 執行完畢。
pause
exit /b 0

:error
echo.
echo [狀態] 流程中斷。
pause
exit /b 1
