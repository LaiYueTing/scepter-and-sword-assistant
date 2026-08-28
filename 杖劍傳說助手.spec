# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包設定。

    pyinstaller --noconfirm 杖劍傳說助手.spec

⚠ **為什麼需要 .spec 而不是純命令列參數。** `--splash` 從命令列產生的設定裡
  `text_pos=None`，那會**關掉動態文字**——`pyi_splash.update_text()` 就沒有地方可
  以畫，進度條也就不存在。只有在這裡明寫 `text_pos` 才拿得到那一行。

⚠ `text_pos` / `text_size` / `text_color` 要和 `make_splash.py` 的版面對齊。
  `tools/make_splash.py` 會在產生圖之後把該填的數字印出來，改版面時照著更新。

其餘設定和原本的命令列參數一一對應：單檔、視窗模式、腳本／模板／adb 全部內嵌。
"""

BUNDLE = [
    ("scripts", "scripts"),
    ("templates", "templates"),
    ("platform-tools", "platform-tools"),
    ("config.example.yaml", "."),
    ("assets/icon.ico", "."),
    # 介面的前端。⚠ 這是 `npm run build` 的產物，**不在版本控制裡**——build.bat 會
    #   先跑它並在失敗時中止，漏跑的話這裡會找不到檔案而編不下去。那正是要的：
    #   寧可編不出來，也不要打包出一個載入空白頁的 EXE。
    ("gui/web", "gui/web"),
]

# ⚠ tkinter 只有啟動畫面那一層在用（PyInstaller 的 Splash 需要 Tcl/Tk），
#   我們自己的程式碼一行都沒有 import 它，所以排除掉不影響任何功能。
EXCLUDES = ["tkinter"]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=BUNDLE,
    hiddenimports=["cv2", "numpy", "yaml"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# 啟動畫面。text_pos 一定要給，給了才有 update_text 可用（見檔頭）。
splash = Splash(
    "assets/splash.png",
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(20, 249),
    text_size=9,
    text_color="#B6BECB",
    # 我們的第一個 step() 之前（bootloader 還沒開始寫檔名）顯示這句，
    # 免得那條暗帶是空的。
    text_default="正在啟動 …",
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.datas,
    [],
    name="杖劍傳說助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # --windowed：雙擊不會有黑視窗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/icon.ico"],
    version="assets/version_info.txt",
)
