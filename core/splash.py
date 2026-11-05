"""啟動畫面的進度回報。畫面由 PyInstaller 的 Splash 顯示，進度條與動畫在 `assets/splash.tcl`。

⚠ 不可 import 任何重量級模組，要在載入 cv2 與介面之前就能回報。
⚠ STAGES 的百分比依各階段的實際耗時分配，改動 import 順序或相依時要重新量。
"""

from __future__ import annotations

# 各階段的名稱與「走到這裡時已經完成多少」。解壓階段沒有人回報，由 splash.tcl 照時間往前爬。
STAGES: dict[str, int] = {
    "載入程式庫": 42,
    "載入介面": 58,
    "建立視窗": 72,
    "載入畫面": 88,
    "完成": 100,
}


def _pyi():
    """取得 pyi_splash，未打包或沒帶 --splash 時回傳 None。"""
    try:
        import pyi_splash                       # type: ignore[import-not-found]
    except Exception:
        return None
    return pyi_splash


def step(name: str) -> None:
    """回報「正在做什麼」，並把進度條推到該階段的百分比。

    名稱不在 STAGES 裡也能用（只換文字、不改變進度）。
    """
    mod = _pyi()
    if mod is None:
        return
    pct = STAGES.get(name)
    try:
        mod.update_text(f"{'' if pct is None else pct}|{name}")
    except Exception:
        # 啟動畫面已關閉或 Tk 出錯，都不影響啟動流程
        pass


def close() -> None:
    """關閉啟動畫面。

    ⚠ 每一條開不了視窗的路徑都要呼叫（已有實例在跑、設定檔損毀、命令列子命令）。
    """
    mod = _pyi()
    if mod is None:
        return
    try:
        mod.close()
    except Exception:
        pass
