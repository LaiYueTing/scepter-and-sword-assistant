"""啟動畫面的進度回報。

雙擊到視窗出現要六秒。PyInstaller 的 Splash 讓 bootloader 在解壓時就把畫面顯示出來，
進度條與動畫由 `assets/splash.tcl` 畫，這支模組只負責告訴它走到哪了。

⚠ 這支模組不能 import 任何重的東西，它的用途是在載入 cv2 與介面之前就讓畫面有反應。

⚠ STAGES 的百分比依各階段的實際耗時分配。改動 import 順序或加了重量級相依時要重新量。
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
        # 啟動畫面已經被關掉、或 Tk 那頭出了問題，都不該影響啟動流程
        pass


def close() -> None:
    """關掉啟動畫面。

    ⚠ **每一條啟動路徑都要呼叫**，包含開不了視窗的那些（已經有實例在跑、設定檔
      壞掉、命令列子命令）。漏掉的話那張圖會留在螢幕上直到行程結束。
    """
    mod = _pyi()
    if mod is None:
        return
    try:
        mod.close()
    except Exception:
        pass
