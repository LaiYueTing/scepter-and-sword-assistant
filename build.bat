@echo off
title Build 杖劍傳說助手
color 3f

cd /d "%~dp0"

rem 設定專案變數
set "PROJECT_NAME=杖劍傳說助手"
set "SCRIPT_NAME=main.py"
set "ICON_NAME=icon.ico"
set "VERSION_FILE=version_info.txt"
set "SPEC_FILE=杖劍傳說助手.spec"

echo [資訊] 開始進行編譯程序 ...
echo [資訊] 專案名稱：%PROJECT_NAME%

rem 前置檔案檢查
if not exist "%SCRIPT_NAME%" (
    echo [錯誤] 找不到主要開發檔案：%SCRIPT_NAME%
    goto :error
)

if not exist "%VERSION_FILE%" (
    echo [錯誤] 找不到版本資訊檔案：%VERSION_FILE%
    goto :error
)

rem 打包設定寫在 .spec 裡（圖示、啟動畫面、要內嵌哪些資料夾）。
rem ※ 啟動畫面的動態進度文字一定要走 .spec：命令列的 --splash 產生的
rem    設定是 text_pos=None，那會關掉 update_text，進度條就不存在。
if not exist "%SPEC_FILE%" (
    echo [錯誤] 找不到打包設定：%SPEC_FILE%
    goto :error
)
if not exist "splash.png" (
    echo [提示] 沒有 splash.png，可執行 python make_splash.py 產生
)

rem 檢查 PyInstaller
python -c "import PyInstaller" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [警告] 尚未安裝 PyInstaller，正在安裝 ...
    python -m pip install pyinstaller
    if %ERRORLEVEL% neq 0 (
        echo [錯誤] PyInstaller 安裝失敗
        goto :error
    )
)

rem 網頁介面的前端要先建置。
rem ※ 這一步**失敗就必須中止**，不能只印個警告帶過：.spec 會把 gui\web
rem    整個內嵌進 EXE，而那是 npm 的產物、不在版本控制裡。漏跑的那天，打包出來
rem    的會是上一版的介面（或根本沒有介面）而且完全沒有徵兆——這正是當初拒絕
rem    加 build step 的理由，加一道硬中止就解掉了。
rem ※ 沒裝 Node 的人：拿掉這一段，並在 .spec 的 BUNDLE 裡移除 gui\web，
rem    就會編出一顆只有 Qt 介面的 EXE。
where npm >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [錯誤] 找不到 npm。網頁介面的前端需要 Node.js 才能建置。
    goto :error
)
if not exist "gui\ui\node_modules" (
    echo [資訊] 第一次建置，正在安裝前端相依 ...
    pushd gui\ui
    call npm install
    popd
)
echo [資訊] 建置網頁介面的前端 ...
pushd gui\ui
call npm run build
set "WEB_BUILD=%ERRORLEVEL%"
popd
if not "%WEB_BUILD%"=="0" (
    echo [錯誤] 前端建置失敗，中止編譯。
    goto :error
)
if not exist "gui\web\index.html" (
    echo [錯誤] 前端建置沒有產出 gui\web\index.html，中止編譯。
    goto :error
)

rem 自動遞增版本號（patch +1）
echo [資訊] 自動遞增版本號 ...
python tools\bump_version.py
if %ERRORLEVEL% neq 0 (
    echo [警告] 版本號遞增失敗，使用現有版本繼續編譯
)

echo [資訊] 啟動 PyInstaller 編譯程序 ...

rem 執行編譯指令
rem 註：--windowed 是刻意的。雙擊 EXE 開介面時完全不會有黑視窗——
rem     onefile 解壓那幾秒我們的程式還沒開始跑，藏視窗再早都追不上。
rem     命令列模式仍然可用：main.py 會 AttachConsole 接上呼叫者的
rem     終端機（見 core/logger.py 的 attach_console）。
rem 註：腳本 / 模板 / adb / 設定範本全部打包進 EXE，發布時只需要那一個檔案。
rem     唯一留在外面的是 config.yaml（含個人 IP），程式第一次執行會自動產生。
rem     想改腳本或換掉某個模板，在 EXE 旁邊放 scripts\ 或 templates\ 同名檔案
rem     即可覆蓋內建的那份，不必重新編譯（逐檔覆蓋，見 core/config.py）。
pyinstaller ^
    --noconfirm ^
    --clean ^
    "%SPEC_FILE%"

rem 檢查 PyInstaller 回傳狀態碼
if %ERRORLEVEL% neq 0 (
    echo [錯誤] PyInstaller 編譯失敗，請檢查上方的錯誤訊息。
    goto :error
)

rem 驗證最終輸出檔案
if not exist "dist\%PROJECT_NAME%.exe" (
    echo [錯誤] 編譯程序回傳成功，但在 dist 資料夾中找不到輸出檔案。
    goto :error
)

rem 清掉上一次打包殘留在 dist 的東西。
rem 個人設定檔絕對不能留（含 IP）；舊的外部 scripts / templates 也要清——
rem 它們會覆蓋 EXE 內建的新版本，造成「明明改了卻沒生效」的怪問題。
echo [資訊] 清理 dist 的殘留檔案 ...
if exist "dist\config.yaml"         del /q "dist\config.yaml"
if exist "dist\config.example.yaml" del /q "dist\config.example.yaml"
if exist "dist\logs"               rmdir /s /q "dist\logs"
if exist "dist\scripts"            rmdir /s /q "dist\scripts"
if exist "dist\templates"          rmdir /s /q "dist\templates"
if exist "dist\platform-tools"     rmdir /s /q "dist\platform-tools"
if exist "dist\icon.ico"          del /q "dist\icon.ico"

echo [成功] 編譯完成！
echo [資訊] 檔案路徑：dist\%PROJECT_NAME%.exe
echo [資訊] 這是單一執行檔，複製它到任何電腦即可執行
echo [資訊] 雙擊執行會開啟圖形介面；帶參數則走命令列，例如 run
echo [資訊] 第一次執行會在旁邊自動產生 config.yaml，填入模擬器 IP 後即可使用
goto :end

:error
echo [狀態] 編譯流程中斷。
pause
exit /b 1

:end
echo [狀態] 編譯流程完成。
pause
exit /b 0
