"""產生 assets/splash.png：EXE 啟動時 bootloader 顯示的載入畫面。

    python tools/make_splash.py

換過底圖或改過版面時才要跑一次，平常不必。

⚠ **這支工具需要 PySide6，而它不是助手的執行相依。** 中文字要用系統字型畫，
  而 OpenCV 的 `putText` 畫不出中文（會變成問號），所以文字是用 Qt 的 QPainter
  畫進去的。助手本身早就不用 Qt 了，但這裡的輸出是一張圖、跑完就結束，
  為了它去換一套繪圖工具不划算。缺的話裝：

      python -m pip install PySide6-Essentials

⚠ 這張圖必須由 **bootloader** 顯示，不能等程式自己畫：雙擊到視窗出現約 6 秒，
  其中大半是 bootloader 在解壓，那時我們的 Python 還沒開始跑。PyInstaller 的
  `Splash` 正是掛在那一層。
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "assets" / "splash.png"

# 底圖。放一張 loading.png 進 assets/ 就會用它，尺寸等比縮成 480x270。
#
# ⚠ **版本控制裡沒有這個檔案。** 遊戲的美術素材不隨原始碼發布，所以 clone 下來
#   之後這裡是空的——沒有底圖時改畫一張純色的漸層底，一樣能編譯得出來。
#   想換成自己的圖就放一張 loading.png 進 assets/ 再跑一次。
#
# ⚠ 換圖時如果連尺寸也改了，**要重新產生 splash.png 並更新杖劍傳說助手.spec 的
#   text_pos**——那行動態進度文字的座標是照這個版面算的。本檔最後會把數字印出來。
SOURCE = Path(__file__).resolve().parent.parent / "assets" / "loading.png"
W, H = 480, 270

BAR_H = 56                       # 底部 loading 區。動態進度文字由 PyInstaller
                                 # 畫在這裡（見 TEXT_POS）
BAR_ALPHA = 0.82

ACCENT = (0xFF, 0xC2, 0x4C)      # #4CC2FF，和主視窗同一個主色（OpenCV 是 BGR）
BG = (0x1D, 0x18, 0x16)          # #16181D
BORDER = (0x3D, 0x33, 0x2E)      # #2E333D


def draw_base() -> np.ndarray:
    """底圖，底部壓一條半透明暗帶當 loading 區。

    有 loading.png 就用它，沒有就畫一張純色漸層——版本控制裡沒有那張圖，
    而編譯不該因為缺一張裝飾用的底圖就失敗。
    """
    if SOURCE.is_file():
        src = cv2.imdecode(np.fromfile(str(SOURCE), np.uint8), cv2.IMREAD_COLOR)
        img = cv2.resize(src, (W, H), interpolation=cv2.INTER_AREA)
    else:
        print(f"[資訊] 沒有 {SOURCE.name}，改用純色底圖")
        img = np.zeros((H, W, 3), np.uint8)
        top, bottom = np.array(BG, np.float32), np.array(ACCENT, np.float32) * 0.22
        for y in range(H):                      # 由上而下漸層，帶一點主色
            img[y, :] = top + (bottom - top) * (y / (H - 1))

    bar = img[H - BAR_H:, :].astype(np.float32)
    dark = np.zeros_like(bar)
    dark[:] = BG
    img[H - BAR_H:, :] = (bar * (1 - BAR_ALPHA) + dark * BAR_ALPHA).astype(np.uint8)
    cv2.line(img, (0, H - BAR_H), (W, H - BAR_H), ACCENT, 2, cv2.LINE_AA)
    cv2.rectangle(img, (0, 0), (W - 1, H - 1), BORDER, 2)
    return img


# 微軟正黑體。⚠ 一定要顯式載入：這支工具通常在離屏平台跑（QT_QPA_PLATFORM=
# offscreen），而離屏平台**沒有系統字型**，中文會全部變成豆腐方塊。
FONT_FILE = "C:/Windows/Fonts/msjh.ttc"


def add_text(img: np.ndarray) -> np.ndarray:
    """把中文標題畫上去。OpenCV 畫不了中文，借 Qt 的 QPainter。"""
    from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter, QColor

    family = "Microsoft JhengHei"
    fid = QFontDatabase.addApplicationFont(FONT_FILE)
    if fid >= 0:
        fams = QFontDatabase.applicationFontFamilies(fid)
        if fams:
            family = fams[0]

    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).copy()
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()

    p = QPainter(qimg)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    # ⚠ 底部那條 loading 區**整條留給動態文字**（階段 ＋ 進度條 ＋ 百分比），
    #   由 pyi_splash 在執行時畫上去，位置見 TEXT_POS。這裡不要在同一條裡再烘
    #   一行靜態文字——PyInstaller 的文字是 `-anchor sw`（左下角定位），和 Qt 的
    #   基線對不齊，兩行看起來就是上下錯開的。
    #
    # ⚠ 名稱要有陰影。底圖是明亮的插畫，白字直接畫上去在淺色處會糊掉。
    from PySide6.QtGui import QFontMetrics

    f = QFont(family, 17, QFont.Weight.Bold)
    p.setFont(f)
    x, y = 20, H - BAR_H - 16
    p.setPen(QColor(0, 0, 0, 190))
    p.drawText(x + 2, y + 2, "杖劍傳說助手")
    p.setPen(QColor("#FFFFFF"))
    p.drawText(x, y, "杖劍傳說助手")

    p.end()

    qimg = qimg.convertToFormat(QImage.Format.Format_RGB888)
    buf = np.frombuffer(qimg.constBits(), np.uint8)
    out = buf.reshape((qimg.height(), qimg.bytesPerLine()))[:, : w * 3]
    return cv2.cvtColor(out.reshape((h, w, 3)), cv2.COLOR_RGB2BGR)


# 動態進度文字的位置（給 .spec 的 Splash(text_pos=...) 用）。
# ⚠ 這兩個數字和上面的版面綁在一起：改了 BAR_H 或「助手」的位置就要跟著調，
#   否則文字會壓到 logo 或掉出圖外。
TEXT_POS = (20, H - 21)
TEXT_SIZE = 9
TEXT_COLOR = "#B6BECB"


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("[錯誤] 這支工具要用 PySide6 畫中文字（助手本身不需要它）。")
        print("       安裝：python -m pip install PySide6-Essentials")
        return 1

    app = QApplication.instance() or QApplication([])
    img = add_text(draw_base())
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        print("[錯誤] PNG 編碼失敗")
        return 1
    OUT.write_bytes(buf.tobytes())
    print(f"[資訊] 已產生 {OUT}（{W}x{H}）")
    print(f"[資訊] .spec 要用的：text_pos={TEXT_POS} "
          f"text_size={TEXT_SIZE} text_color={TEXT_COLOR!r}")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
