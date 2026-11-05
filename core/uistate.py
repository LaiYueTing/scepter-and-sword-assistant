"""圖形介面的偏好（ui.json）：主題、視窗大小、關閉時的選擇。腳本行為設定在 config.yaml。

⚠ 檔案不見或內容損毀時一律回到預設值。
"""

from __future__ import annotations

import json
from typing import Any

from core.config import ROOT

PATH = ROOT / "ui.json"

DEFAULTS: dict[str, Any] = {
    "theme": "dark",                       # dark | light
    # 背景漸層主題的 id（見 gui/ui/src/data/gradients.js），"default" 表示純色底。
    # 無法辨識的 id 由前端退回 default。
    "bg_theme": "default",
    # 燈號動畫：breathe（呼吸）/ none（靜態）。系統的 prefers-reduced-motion 由 CSS 無條件遵守。
    "glow": "breathe",
    "bounds": {"width": 1180, "height": 840},
    # 關閉視窗時要做什麼：ask（每次問）/ tray（縮到背景）/ quit（直接結束）
    "on_close": "ask",
    # 縮到系統匣時是否跳氣泡通知。點那則通知等於關閉（見 gui/tray.py）。
    "tray_hint": True,
}


def load() -> dict[str, Any]:
    data = dict(DEFAULTS)
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data.update({k: v for k, v in raw.items() if k in DEFAULTS})
    except Exception:
        pass                # 不存在或損毀都當成還沒設定
    return data


def get(key: str) -> Any:
    return load().get(key, DEFAULTS.get(key))


def set(key: str, value: Any) -> None:        # noqa: A001  和 get 對稱，刻意同名
    if key not in DEFAULTS:
        return              # 不認得的鍵不寫
    data = load()
    data[key] = value
    try:
        PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError:
        pass                # 寫入失敗時下次回到預設值
