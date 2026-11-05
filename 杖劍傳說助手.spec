# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包設定：單檔、視窗模式，腳本、模板、adb 全部內嵌。

    pyinstaller --noconfirm 杖劍傳說助手.spec

⚠ 不可改用純命令列參數：`--splash` 的 `text_pos=None` 會關閉動態文字。
⚠ 載入畫面的進度條與動畫在 `assets/splash.tcl`，由這裡併進 Tcl 腳本。底圖由 `tools/make_splash.py` 產生。
"""

BUNDLE = [
    ("scripts", "scripts"),
    ("templates", "templates"),
    ("platform-tools", "platform-tools"),
    ("config.example.yaml", "."),
    ("assets/icon.ico", "."),
    # 介面的前端，`npm run build` 的產物（不進版控），build.bat 會先建置。
    ("gui/web", "gui/web"),
]

# ⚠ 啟動畫面的 Tcl/Tk 由 PyInstaller 的 Splash 帶入，程式碼不 import tkinter。
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


def _splash_script(text_options=None, always_on_top=False):
    """PyInstaller 的啟動畫面腳本，文字行換成 assets/splash.tcl。"""
    import re
    from pathlib import Path
    from PyInstaller.building import splash_templates as tpl
    version = re.search(r'^VERSION = "(.+)"', Path("core/config.py").read_text(encoding="utf-8"), re.M)
    tcl = Path("assets/splash.tcl").read_text(encoding="utf-8").replace("@VERSION@", version.group(1))
    return "\n".join([tpl.ipc_script, tpl.image_script, tpl.splash_canvas_setup, tcl,
                      tpl.transparent_setup, tpl.pack_widgets,
                      tpl.position_window_on_top if always_on_top else tpl.position_window,
                      tpl.raise_window])


from PyInstaller.building import splash_templates as _splash_templates
_splash_templates.build_script = _splash_script

splash = Splash(
    "assets/splash.png",
    binaries=a.binaries,
    datas=a.datas,
    # text_pos 要給，update_text 才能用；文字由 splash.tcl 畫。
    text_pos=(0, 0),
    text_size=9,
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
