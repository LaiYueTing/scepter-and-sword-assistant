"""啟動畫面的進度回報。

雙擊到視窗出現要六秒，全黑六秒看起來像沒反應。PyInstaller 的 `--splash` 讓
bootloader 在解壓時就把圖顯示出來，這支模組負責在那張圖上更新進度文字。

⚠ **這支模組不能 import 任何重的東西。** 它的用途正是「在載入 cv2 與介面之前
  先讓畫面動起來」，自己拖慢啟動就本末倒置了——只用標準庫。

⚠ **進度不是猜的。** 每一段的百分比是實測各階段耗時之後填的（見 STAGES），
  所以進度條會照著真實速度走。改動 import 順序或加了新的重量級相依時，要重新
  量一次並更新那張表，否則進度條會在某一段卡住不動。

⚠ **有一段報不出來**：bootloader 解壓的那幾秒，我們的 Python 還沒開始跑，沒有
  任何程式可以回報。那段圖上顯示的是 `splash.png` 本身烘進去的文字。
"""

from __future__ import annotations

# 各階段的名稱與「走到這裡時已經完成多少」。
#
# ⚠ 百分比是**實測各階段耗時之後**填的，不是平均分配。實測（112 MB 的 EXE）：
#   0～3.5 秒是 bootloader 解壓（那段這條進度條還沒出現，畫面上是 bootloader
#   自己寫的檔名），3.5～3.8 秒跑完我們的 import 與設定，3.8～6 秒都在建視窗。
#   所以後半那幾段要拉開——照階段數平均分配的話，進度條會在 0.3 秒內衝到九成，
#   然後在同一個數字上停兩秒，看起來就像當掉了。
STAGES: dict[str, int] = {
    "載入程式庫": 20,
    "讀取設定": 35,
    "建立介面": 45,
    "準備視窗": 55,
    "版面配置": 75,
    "套用外觀": 90,
    "完成": 100,
}

BAR_CELLS = 16                  # 進度條用幾格。太多格在小圖上會擠成一片。

# ⚠ 填滿與空白要選**筆畫粗細差很多**的字元。pyi_splash 只能指定一種文字顏色，
#   分不出深淺——用 █／░ 的話兩者在小字級下幾乎一樣重，整條看起來像一塊灰。
_FILLED, _EMPTY = "█", "·"


def _pyi():
    """取得 pyi_splash，未打包或沒帶 --splash 時回傳 None。"""
    try:
        import pyi_splash                       # type: ignore[import-not-found]
    except Exception:
        return None
    return pyi_splash


def step(name: str) -> None:
    """回報「正在做什麼」，並把進度條推到該階段的百分比。

    名稱不在 STAGES 裡也能用（當成不改變進度的補充說明），但正常情況應該用
    表裡的那幾個——那樣進度才會單調前進。
    """
    mod = _pyi()
    if mod is None:
        return
    pct = STAGES.get(name)
    try:
        if pct is None:
            mod.update_text(name)
        else:
            done = round(BAR_CELLS * pct / 100)
            bar = _FILLED * done + _EMPTY * (BAR_CELLS - done)
            mod.update_text(f"{name} …  {bar}  {pct}%")
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
