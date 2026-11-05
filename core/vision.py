"""影像比對層：在畫面上尋找模板圖片。解析度固定 720x1280，用單一尺度比對。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import yaml

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
    """依名稱載入模板，結果會快取（不設上限，全部留著只有幾 MB）。

    EXE 旁邊放同名檔案可以覆蓋，見 config.resource_file。
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


@lru_cache(maxsize=1)
def _search_regions() -> dict[str, Region]:
    """固定 UI 元素的預設搜尋範圍（templates/search_regions.yaml），由 tools/gen_search_regions.py 產生。

    全畫面彩色比對一次約 60ms。沒列在表上的模板掃全畫面。
    """
    path = resource_file("templates", "search_regions.yaml")
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {name: tuple(r) for name, r in raw.items()}


def search_region(template: str | np.ndarray, region: Region | None) -> Region | None:
    """呼叫端沒指定 region 時，換成模板的預設搜尋範圍（沒有就是全畫面）。"""
    if region or not isinstance(template, str):
        return region
    return _search_regions().get(Path(template).stem)


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
    hint: bool = True,
) -> Match | None:
    """在畫面中尋找模板，回傳分數最高且超過門檻的結果。

    `region` 省略時使用模板的預設搜尋範圍；`hint=False` 強制掃全畫面（除錯用）。
    """
    name = template if isinstance(template, str) else "<array>"
    tmpl = load_template(template) if isinstance(template, str) else template
    if hint:
        region = search_region(template, region)

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
    hint: bool = True,
) -> list[Match]:
    """尋找所有符合的位置，重疊結果會被抑制。`region` 與 `hint` 同 find。"""
    name = template if isinstance(template, str) else "<array>"
    tmpl = load_template(template) if isinstance(template, str) else template
    if hint:
        region = search_region(template, region)

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
    """量指定區域裡有幾欄接近某個顏色，回傳欄數（順序條的空軌道長度）。

    某一欄有 fill 比例以上的像素接近目標色就算命中，不受上下緣反鋸齒與箭頭裝飾影響。
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
    """估計順序條上排了幾個單位，回傳估計值。

        單位數 ≈ （已排到的寬度）÷（圖示間距）

    空軌道長度在約 12 個單位以上會飽和成 0，圖示間距仍然單調（48px → 14px）。間距用自相關求。

    ⚠ 自相關峰值只有 0.3～0.6，單幀讀數相鄰可差到 20 個單位，呼叫端要配 smooth 與 sustain。
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
    # 間距的合理範圍：最寬 48px（空位多）、最窄 14px（排滿）
    lo, hi = 12, 60
    pitch = lo + int(np.argmax(ac[lo:hi]))
    return filled / pitch


def find_blob(screen: np.ndarray, spec: dict,
              avoid: list[tuple[int, int]] | None = None) -> Match | None:
    """找畫面上最大的一塊指定顏色，回傳外框；不夠大就回傳 None。

    用於沒有固定圖案的元素：虛空裂縫的門模板只有 0.72～0.85，核心顏色 H≈129、S≈190 極穩定，
    門 5200～6750 像素，沒有門的地圖 ≤12 像素。

    欄位（HSV 用 OpenCV 的尺度：H 0～180、S/V 0～255）：
        hue       [lo, hi]　色相範圍，必填
        sat       [lo, hi]　飽和度範圍，預設 [150, 255]
        val       [lo, hi]　明度範圍，預設 [0, 255]
        region    [x, y, w, h]　只在這一帶找
        exclude   [[x, y, w, h], …]　排除的區域（同色的 UI 元件）
        min_area  至少要這麼多像素才算，預設 1000

    `avoid` 是要跳過的位置：中心落在任一點 AVOID_RADIUS 像素內的色塊不算，改取次大的。
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
    # 開運算去掉雜點，避免把不相干的色塊連在一起
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    min_area = int(spec.get("min_area", 1000))
    for i in sorted(range(1, count), key=lambda k: -stats[k, cv2.CC_STAT_AREA]):
        size = int(stats[i, cv2.CC_STAT_AREA])
        if size < min_area:
            return None
        bx, by, bw, bh = (int(stats[i, k]) for k in (
            cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        found = Match("blob", float(size), bx + x0, by + y0, bw, bh)
        cx, cy = found.center
        if any((cx - ax) ** 2 + (cy - ay) ** 2 <= AVOID_RADIUS ** 2
               for ax, ay in avoid or ()):
            continue
        return found
    return None


# find_blob 的 avoid 半徑：門的寬度約 100px，兩扇門相距遠大於此。
AVOID_RADIUS = 90


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
