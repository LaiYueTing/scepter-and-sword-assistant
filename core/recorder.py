"""流程錄製：連續抓幀，只留下畫面真正有變化的關鍵幀。

用途是快速摸清一段遊戲流程有哪些畫面。逐張手動截圖太慢，
但把每一幀都留下來又會被戰鬥動畫淹沒，所以這裡用畫面差異當過濾器，
只保留「轉場」那幾張，最後再拼成一張總覽圖方便一次看完。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import logger, vision
from .adb import Device
from .config import LOG_DIR

log = logger.get("recorder")


@dataclass
class Frame:
    index: int
    elapsed: float                  # 從開始錄製算起的秒數
    image: np.ndarray | None        # 已寫檔的幀不留在記憶體，需要時再讀回
    diff: float                     # 與前一張保留的幀相差多少


def frame_diff(a: np.ndarray, b: np.ndarray) -> float:
    """兩張畫面的平均像素差，0 表示完全相同。"""
    if a.shape != b.shape:
        return 255.0
    return float(np.mean(cv2.absdiff(a, b)))


def record(
    device: Device,
    duration: float = 60.0,
    interval: float = 0.4,
    threshold: float = 6.0,
    max_frames: int = 24,
    save_dir: Path | None = None,
) -> list[Frame]:
    """錄製一段流程，回傳有變化的關鍵幀。

    threshold 是判定「畫面換了」的平均像素差門檻。戰鬥特效會讓畫面
    持續小幅變動，門檻太低會塞滿無意義的幀，建議 5~10。

    給了 save_dir 就會邊錄邊寫檔，中途按 Ctrl + C 或被中斷也不會丟資料。
    """
    frames: list[Frame] = []
    started = time.time()
    prev: np.ndarray | None = None
    captured = 0

    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)

    log.info("開始錄製：%.0f 秒，間隔 %.1f 秒，變化門檻 %.1f",
             duration, interval, threshold)

    try:
        while time.time() - started < duration:
            loop_start = time.time()
            img = device.screencap()
            captured += 1
            elapsed = loop_start - started

            d = 255.0 if prev is None else frame_diff(prev, img)
            if d >= threshold:
                frame = Frame(len(frames), elapsed, img, d)
                if save_dir:
                    vision.imwrite_unicode(save_dir / _frame_name(frame), img)
                    # ⚠ 已經落地就要從記憶體釋放。一張 720x1280 解碼後約 2.7MB，
                    #   錄十分鐘累積到好幾百 MB，會把 OpenCV 撐爆。
                    frame.image = None
                frames.append(frame)
                prev = img
                # 逐幀進度只印終端機，不寫紀錄檔。錄製是開發用的互動指令，一段
                # 十幾分鐘的錄製會寫上千行——實測 assistant.log 有 95% 是這種行，
                # 把實機執行的紀錄整段推出輪替範圍。摘要留在紀錄裡就夠了。
                print(f"  第 {len(frames)} 幀　{elapsed:.1f} 秒　差異 {d:.1f}")

            # 扣掉截圖本身耗掉的時間，讓間隔比較接近設定值
            rest = interval - (time.time() - loop_start)
            if rest > 0:
                time.sleep(rest)
    except KeyboardInterrupt:
        log.info("使用者中斷錄製，保留已抓到的畫面")

    log.info("錄製結束：共抓 %d 張，保留 %d 張關鍵幀", captured, len(frames))

    if len(frames) > max_frames:
        # 均勻抽樣，保留頭尾
        idx = np.linspace(0, len(frames) - 1, max_frames).round().astype(int)
        frames = [frames[i] for i in dict.fromkeys(idx.tolist())]
        log.info("關鍵幀過多，均勻縮減為 %d 張", len(frames))

    return frames


def _frame_name(f: Frame) -> str:
    return f"{f.index:02d}_{f.elapsed:06.1f}s.png"


def record_dir(name: str) -> Path:
    return LOG_DIR / "records" / name


def load_frames(
    folder: Path,
    max_frames: int = 36,
    start: int = 0,
    count: int | None = None,
) -> list[Frame]:
    """從已存檔的錄製資料夾讀回關鍵幀（錄製被中斷時用來補做總覽圖）。

    先抽樣再讀檔，避免把幾百張全解碼進記憶體。抽樣會濾掉只出現一瞬間的畫面
    （提示、彈窗），要逐張看完時用 start/count 分批取。
    """
    files = sorted(folder.glob("*.png"), key=lambda p: int(p.stem.split("_")[0]))
    if not files:
        return []

    files = files[start:] if count is None else files[start:start + count]
    if not files:
        return []

    if len(files) > max_frames:
        idx = np.linspace(0, len(files) - 1, max_frames).round().astype(int)
        files = [files[i] for i in dict.fromkeys(idx.tolist())]

    frames = []
    for p in files:
        index, _, rest = p.stem.partition("_")
        elapsed = float(rest.rstrip("s")) if rest else 0.0
        frames.append(Frame(int(index), elapsed, vision.imread_unicode(p), 0.0))
    return frames


def contact_sheet(
    frames: list[Frame],
    cols: int = 4,
    thumb_width: int = 200,
    label_height: int = 22,
) -> np.ndarray:
    """把關鍵幀拼成一張總覽圖，每格標上編號與時間。"""
    if not frames:
        raise ValueError("沒有可用的關鍵幀")

    h, w = frames[0].image.shape[:2]
    tw = thumb_width
    th = int(round(h * tw / w))
    cell_h = th + label_height

    rows = (len(frames) + cols - 1) // cols
    sheet = np.full((rows * cell_h, cols * tw, 3), 32, np.uint8)

    for i, f in enumerate(frames):
        r, c = divmod(i, cols)
        y0, x0 = r * cell_h, c * tw

        thumb = cv2.resize(f.image, (tw, th), interpolation=cv2.INTER_AREA)
        sheet[y0:y0 + th, x0:x0 + tw] = thumb

        text = f"#{f.index}  {f.elapsed:.1f}s"
        cv2.putText(
            sheet, text, (x0 + 5, y0 + th + 16),
            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (230, 230, 230), 1, cv2.LINE_AA,
        )
        # 格線，避免相鄰縮圖黏在一起分不清
        cv2.rectangle(sheet, (x0, y0), (x0 + tw - 1, y0 + th - 1), (90, 90, 90), 1)

    return sheet
