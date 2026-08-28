"""產生一個預設的 icon.ico 給 build.bat 使用。

只用 OpenCV 畫圖，再手工組出 ICO 檔頭，不需要額外裝 Pillow。
想換成自己的圖示，直接把 icon.ico 覆蓋掉即可。
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
SIZES = (16, 32, 48, 64, 128, 256)


def draw(size: int) -> np.ndarray:
    """畫一把劍疊在圓底上，回傳 BGRA 影像。"""
    s = 256                                   # 先用大尺寸畫再縮，邊緣比較乾淨
    img = np.zeros((s, s, 4), np.uint8)

    cv2.circle(img, (128, 128), 120, (60, 45, 30, 255), -1)      # 深色圓底
    cv2.circle(img, (128, 128), 120, (150, 200, 230, 255), 8)    # 外框

    # 劍身
    blade = np.array([[128, 30], [148, 60], [148, 165], [128, 185],
                      [108, 165], [108, 60]], np.int32)
    cv2.fillPoly(img, [blade], (235, 245, 250, 255))
    cv2.polylines(img, [blade], True, (120, 140, 160, 255), 3)

    # 護手與握把
    cv2.rectangle(img, (78, 165), (178, 185), (60, 170, 220, 255), -1)
    cv2.rectangle(img, (78, 165), (178, 185), (30, 110, 160, 255), 3)
    cv2.rectangle(img, (118, 185), (138, 225), (50, 90, 140, 255), -1)
    cv2.circle(img, (128, 228), 12, (60, 170, 220, 255), -1)

    return cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)


def png_bytes(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG 編碼失敗")
    return buf.tobytes()


def build_ico(images: list[np.ndarray]) -> bytes:
    """把多張圖組成一個 ICO。各張以 PNG 內嵌，Vista 之後都支援。"""
    payloads = [png_bytes(im) for im in images]

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)

    entries, body = b"", b""
    for img, data in zip(images, payloads):
        h, w = img.shape[:2]
        entries += struct.pack(
            "<BBBBHHII",
            0 if w >= 256 else w,      # 256 要寫成 0
            0 if h >= 256 else h,
            0, 0, 1, 32,
            len(data), offset,
        )
        body += data
        offset += len(data)

    return header + entries + body


def main() -> int:
    images = [draw(s) for s in SIZES]
    OUT.write_bytes(build_ico(images))
    print(f"[資訊] 已產生圖示：{OUT}")
    print(f"[資訊] 內含尺寸：{', '.join(f'{s}x{s}' for s in SIZES)}")
    print("[提示] 想換圖示就直接覆蓋這個檔案，build.bat 會自動帶入")
    return 0


if __name__ == "__main__":
    sys.exit(main())
