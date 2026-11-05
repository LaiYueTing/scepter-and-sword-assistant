"""產生 assets/splash.png：EXE 啟動時 bootloader 顯示的載入畫面底圖。

    python tools/make_splash.py

換過底圖或改過版面時才要跑一次。進度條與文字是 assets/splash.tcl 在執行時畫的，
這張圖只放底圖、標題與暗部漸層。

⚠ 底圖 assets/loading.png 是遊戲的美術素材，不進版本控制；沒有那張圖時畫純色漸層，
  一樣編譯得出來。

⚠ 圓角的外緣只能是全透明或全不透明。bootloader 用 magenta 當透明色，半透明的邊緣會
  留下一圈粉紅色。

⚠ 尺寸不要超過 760x480，超過時 PyInstaller 會重新縮放而變糊。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "splash.png"
SOURCE = ROOT / "assets" / "loading.png"

W, H = 640, 360
RADIUS = 14
FADE_TOP = 165                   # 暗部漸層從這裡開始
FADE_ALPHA = 0.94                # 最底下的濃度
DARK = (14, 18, 26)
FONT_BOLD = "C:/Windows/Fonts/msjhbd.ttc"
FONT_REGULAR = "C:/Windows/Fonts/msjh.ttc"


def base() -> Image.Image:
    """底圖。沒有 loading.png 就畫一張帶主色的漸層。"""
    if SOURCE.is_file():
        return Image.open(SOURCE).convert("RGB").resize((W, H), Image.LANCZOS)
    print(f"[資訊] 沒有 {SOURCE.name}，改用漸層底圖")
    img = Image.new("RGB", (W, H))
    top, bottom = (28, 44, 66), (14, 18, 26)
    for y in range(H):
        t = y / (H - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        ImageDraw.Draw(img).line([(0, y), (W, y)], fill=color)
    return img


def fade(img: Image.Image) -> Image.Image:
    """底部壓暗，文字與進度條才讀得到。曲線用平方，交界不會有一條線。"""
    mask = Image.new("L", (1, H))
    for y in range(H):
        t = max(0.0, (y - FADE_TOP) / (H - FADE_TOP))
        mask.putpixel((0, y), round(255 * FADE_ALPHA * min(1.0, t * 1.7) ** 1.6))
    return Image.composite(Image.new("RGB", (W, H), DARK), img, mask.resize((W, H)))


def text_with_shadow(img: Image.Image, xy: tuple[int, int], text: str,
                     font: ImageFont.FreeTypeFont, fill: tuple[int, int, int]) -> None:
    """帶柔和陰影的文字（anchor 是左下）。"""
    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).text((xy[0], xy[1] + 2), text, font=font, fill=210, anchor="ls")
    shadow = shadow.filter(ImageFilter.GaussianBlur(4))
    img.paste((0, 0, 0), mask=shadow)
    ImageDraw.Draw(img).text(xy, text, font=font, fill=fill, anchor="ls")


def main() -> int:
    img = fade(base())
    text_with_shadow(img, (26, 292), "杖劍傳說助手", ImageFont.truetype(FONT_BOLD, 34), (255, 255, 255))

    # 外框：圓角遮罩（硬邊）＋一條很淡的內框
    scale = 4
    big = Image.new("L", (W * scale, H * scale), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, W * scale - 1, H * scale - 1), RADIUS * scale, fill=255)
    mask = big.resize((W, H), Image.LANCZOS).point(lambda v: 255 if v >= 128 else 0)

    line = Image.new("L", (W * scale, H * scale), 0)
    ImageDraw.Draw(line).rounded_rectangle(
        (0, 0, W * scale - 1, H * scale - 1), RADIUS * scale, outline=255, width=scale * 2)
    line = line.resize((W, H), Image.LANCZOS).point(lambda v: round(v * 0.16))
    img = Image.composite(Image.new("RGB", (W, H), (255, 255, 255)), img, ImageChops.darker(line, mask))

    out = img.convert("RGBA")
    out.putalpha(mask)
    out.save(OUT, optimize=True)
    print(f"[資訊] 已產生 {OUT}（{W}x{H}，{OUT.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
