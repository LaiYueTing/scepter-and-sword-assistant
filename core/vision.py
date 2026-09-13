"""影像比對層：在畫面上尋找模板圖片。

解析度固定為 720x1280，因此採用單一尺度的模板比對即可，
不需要多尺度搜尋，速度快也夠準。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from . import logger
from .config import resource_file

log = logger.get("vision")

# 區域：(x, y, w, h)
Region = tuple[int, int, int, int]


@dataclass(frozen=True)
class Match:
    """一次成功的比對結果。"""

    name: str
    score: float
    x: int          # 左上角
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


def imread_unicode(path: Path) -> np.ndarray:
    """讀取圖片，支援含中文的路徑（cv2.imread 在 Windows 上會失敗）。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"無法讀取圖片：{path}")
    return img


def imwrite_unicode(path: Path, img: np.ndarray) -> None:
    """寫出圖片，支援含中文的路徑（cv2.imwrite 在 Windows 上會回傳 False 而不拋錯）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(path.suffix or ".png", img)
    if not ok:
        raise ValueError(f"無法編碼圖片：{path}")
    path.write_bytes(buf.tobytes())


@lru_cache(maxsize=None)
def load_template(name: str) -> np.ndarray:
    """依名稱載入模板，結果會快取。

    ⚠ 不設上限。模板有 129 個而舊的上限是 128——差一個，於是每輪都會把最久沒
      用到的那張擠掉，下次用到再重新解一次 PNG。全部留著也只有幾 MB。

    模板打包在 EXE 裡，但 EXE 旁邊放同名檔案可以覆蓋——詳見 config.resource_file。
    """
    stem = Path(name).stem
    for ext in (".png", ".jpg", ".jpeg", ".bmp"):
        p = resource_file("templates", f"{stem}{ext}")
        if p.is_file():
            return imread_unicode(p)
    raise FileNotFoundError(
        f"找不到模板 '{name}'。請用 `python main.py shot` 截圖後，"
        f"裁切目標區塊存成 templates/{stem}.png"
    )


def _crop(screen: np.ndarray, region: Region | None) -> tuple[np.ndarray, int, int]:
    """裁切搜尋區域，回傳 (影像, x 偏移, y 偏移)。"""
    if not region:
        return screen, 0, 0
    x, y, w, h = region
    h_img, w_img = screen.shape[:2]
    x = max(0, min(w_img - 1, x))
    y = max(0, min(h_img - 1, y))
    w = max(1, min(w_img - x, w))
    h = max(1, min(h_img - y, h))
    return screen[y:y + h, x:x + w], x, y


def find(
    screen: np.ndarray,
    template: str | np.ndarray,
    threshold: float = 0.85,
    region: Region | None = None,
) -> Match | None:
    """在畫面中尋找模板，回傳分數最高且超過門檻的結果。"""
    name = template if isinstance(template, str) else "<array>"
    tmpl = load_template(template) if isinstance(template, str) else template

    area, ox, oy = _crop(screen, region)
    th, tw = tmpl.shape[:2]
    if area.shape[0] < th or area.shape[1] < tw:
        log.debug("搜尋區域小於模板 '%s'，略過", name)
        return None

    result = cv2.matchTemplate(area, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    return Match(name, float(max_val), max_loc[0] + ox, max_loc[1] + oy, tw, th)


def find_all(
    screen: np.ndarray,
    template: str | np.ndarray,
    threshold: float = 0.85,
    region: Region | None = None,
    max_results: int = 20,
) -> list[Match]:
    """尋找所有符合的位置，重疊結果會被抑制。"""
    name = template if isinstance(template, str) else "<array>"
    tmpl = load_template(template) if isinstance(template, str) else template

    area, ox, oy = _crop(screen, region)
    th, tw = tmpl.shape[:2]
    if area.shape[0] < th or area.shape[1] < tw:
        return []

    result = cv2.matchTemplate(area, tmpl, cv2.TM_CCOEFF_NORMED)
    matches: list[Match] = []
    ys, xs = np.where(result >= threshold)
    for score, x, y in sorted(
        ((float(result[y, x]), int(x), int(y)) for y, x in zip(ys, xs)),
        reverse=True,
    ):
        # 非極大值抑制：與既有結果重疊超過一半就跳過
        if any(abs(x + ox - m.x) < tw // 2 and abs(y + oy - m.y) < th // 2 for m in matches):
            continue
        matches.append(Match(name, score, x + ox, y + oy, tw, th))
        if len(matches) >= max_results:
            break
    return matches


def exists(
    screen: np.ndarray,
    template: str | np.ndarray,
    threshold: float = 0.85,
    region: Region | None = None,
) -> bool:
    return find(screen, template, threshold, region) is not None


def score(screen: np.ndarray, template: str | np.ndarray, region: Region | None = None) -> float:
    """回傳最佳比對分數，用來調整門檻時很有用。"""
    tmpl = load_template(template) if isinstance(template, str) else template
    area, _, _ = _crop(screen, region)
    th, tw = tmpl.shape[:2]
    if area.shape[0] < th or area.shape[1] < tw:
        return 0.0
    result = cv2.matchTemplate(area, tmpl, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(result)[1])


def color_span(
    screen: np.ndarray,
    region: Region,
    color: tuple[int, int, int],
    tol: int = 22,
    fill: float = 0.6,
) -> int:
    """量指定區域裡「有多少像素寬」接近某個顏色，回傳欄數。

    模板比對認的是圖案，有些東西卻是「長度」在講話——公會討伐的順序條就是這種：
    每一格都是不同玩家的角色與寵物，裁模板等於每遇到一個新玩家就要補一張。
    但沒被圖示佔住的那段空軌道是 UI 元件、顏色極均勻，量它的長度就等於量參戰
    單位的數量（軌道越短、人越多）。量固定的 UI 比認會變的內容可靠。

    以「欄」為單位而不是總像素數，因為要量的是**水平長度**：某一欄只要有 fill
    比例以上的像素接近目標色就算命中，這樣上下緣的反鋸齒、軌道上的箭頭裝飾都
    不會把長度算少。
    """
    area, _, _ = _crop(screen, region)
    diff = np.abs(area.astype(np.int16) - np.array(color, dtype=np.int16))
    near = diff.max(axis=2) <= tol
    return int((near.mean(axis=0) >= fill).sum())


def queue_units(
    screen: np.ndarray,
    region: Region,
    track: tuple[int, int, int],
    hue: tuple[int, int] = (94, 106),
    tol: int = 22,
    fill: float = 0.6,
) -> float:
    """估計順序條上排了幾個單位，回傳估計值（浮點數）。

    `color_span` 量的空軌道長度**會飽和**：圖示多到超過軌道寬度時會自動縮小擠
    進去，約 12 個單位以上就一律是 0，分不出 3 人與 8 人。

    圖示縮小本身就是線索——間距在飽和之後仍然單調（48px → 14px），所以把兩件事
    合起來：

        單位數 ≈ （已排到的寬度）÷（圖示間距）

    間距用自相關求：圖示等距重複，外圈藍的列剖面會有明顯週期。不必知道每個圖示
    長什麼樣，也就不必為任何玩家的角色或寵物裁模板。

    ⚠ 這是估計值不是精確計數。自相關的峰值只有 0.3～0.6（隊列中間的分隔記號會
      破壞週期性），單幀讀數相鄰可能差到 20 個單位——呼叫端一定要配 smooth
      （滑動中位數）與 sustain，不要拿單一讀數做決定。
    """
    x, y, w, h = region
    area, _, _ = _crop(screen, region)

    # 已排到的寬度 = 全寬 - 空軌道
    near = np.abs(area.astype(np.int16) - np.array(track, dtype=np.int16))
    empty = int(((near.max(axis=2) <= tol).mean(axis=0) >= fill).sum())
    filled = area.shape[1] - empty
    if filled <= 0:
        return 0.0

    # 外圈藍的列剖面
    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([hue[0], 110, 130]), np.array([hue[1], 255, 255]))
    sig = mask.mean(axis=0).astype(np.float64)
    sig -= sig.mean()
    if sig.std() < 1e-6:
        return 0.0

    ac = np.correlate(sig, sig, mode="full")[len(sig) - 1:]
    if ac[0] <= 0:
        return 0.0
    ac /= ac[0]
    # 間距的合理範圍：實測最寬 48px（沒人擠）、最窄 14px（塞滿）
    lo, hi = 12, 60
    pitch = lo + int(np.argmax(ac[lo:hi]))
    return filled / pitch


def find_blob(screen: np.ndarray, spec: dict) -> Match | None:
    """找畫面上最大的一塊指定顏色，回傳它的外框；不夠大就回 None。

    模板認的是圖案，而有些東西沒有固定的圖案——虛空裂縫的門是一團會動的紫色
    漩渦，同一個門連拍每一幀都不一樣，模板在各幀只有 0.72～0.85，和對話框裡
    那張大圖差不到 0.06。但它的**顏色**極穩定：核心是 H≈129、S≈190 的飽和紫，
    整張地圖其他地方 S 的 90 百分位只有 85。用顏色找連通區塊，門在 5200～6750
    像素，沒有門的地圖 ≤12 像素。

    欄位（HSV 用 OpenCV 的尺度：H 0～180、S/V 0～255）：
        hue       [lo, hi]　色相範圍，必填
        sat       [lo, hi]　飽和度範圍，預設 [150, 255]
        val       [lo, hi]　明度範圍，預設 [0, 255]
        region    [x, y, w, h]　只在這一帶找
        exclude   [[x, y, w, h], …]　挖掉的區域（同色的 UI 元件）
        min_area  至少要這麼多像素才算，預設 1000

    ⚠ 回傳的是最大的那一塊，不是全部。要的是「門在哪」，而畫面上同色的小碎片
      （粒子、遠處的植物）本來就該被面積門檻擋掉。
    """
    x0, y0 = 0, 0
    region = spec.get("region")
    area, x0, y0 = _crop(screen, tuple(region)) if region else (screen, 0, 0)
    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)
    h_lo, h_hi = spec["hue"]
    s_lo, s_hi = spec.get("sat", (150, 255))
    v_lo, v_hi = spec.get("val", (0, 255))
    mask = cv2.inRange(hsv, np.array([h_lo, s_lo, v_lo]), np.array([h_hi, s_hi, v_hi]))
    for ex in spec.get("exclude") or []:
        ex_x, ex_y, ex_w, ex_h = (int(v) for v in ex)
        mask[max(0, ex_y - y0):max(0, ex_y - y0 + ex_h),
             max(0, ex_x - x0):max(0, ex_x - x0 + ex_w)] = 0
    # 開運算去掉一兩個像素的雜點，免得它們把兩塊不相干的東西連成一塊
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count <= 1:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    size = int(stats[i, cv2.CC_STAT_AREA])
    if size < int(spec.get("min_area", 1000)):
        return None
    bx, by, bw, bh = (int(stats[i, k]) for k in (
        cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
    return Match("blob", float(size), bx + x0, by + y0, bw, bh)


def annotate(screen: np.ndarray, matches: list[Match]) -> np.ndarray:
    """在畫面上標出比對結果，供除錯使用。"""
    canvas = screen.copy()
    for m in matches:
        cv2.rectangle(canvas, (m.x, m.y), (m.x + m.w, m.y + m.h), (0, 255, 0), 2)
        cv2.putText(
            canvas, f"{m.name} {m.score:.2f}", (m.x, max(12, m.y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1, cv2.LINE_AA,
        )
    return canvas
