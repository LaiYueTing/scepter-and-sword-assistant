"""圖形介面自己的偏好：主題、視窗大小、關閉時的選擇。

和 `config.yaml` 是**兩件不同的事**——那份是腳本的行為設定，使用者會拿編輯器去看、
去改，而且註解就是它的說明書。這裡放的是「視窗長什麼樣」，改動頻繁、沒有人會手動編。
混在一起的話，「我的設定到底存在哪」就會變成沒有答案的問題。

⚠ **介面的偏好只存這一份。** 各處各存一份的話，設定就會有兩個來源，而主題
  跳回預設，而使用者不會知道為什麼。

⚠ **壞掉要安全退化。** 檔案不見、內容壞掉，一律回到預設值——這只是外觀，
  絕不能因為它而讓程式起不來。
"""

from __future__ import annotations

import json
from typing import Any

from core.config import ROOT

PATH = ROOT / "ui.json"

DEFAULTS: dict[str, Any] = {
    "theme": "dark",                       # dark | light
    # 背景漸層主題的 id（見 gui/ui/src/data/gradients.js）。
    # "default" ＝ 不套漸層，用內建純色底。認不得的 id 前端會自己退回 default，
    # 所以這裡不必驗證——那份清單只有前端有，搬到後端會變成第二份要跟著維護的表。
    "bg_theme": "default",
    # 燈號要不要呼吸：breathe（會呼吸）/ none（靜態）。
    # ⚠ 這是「喜好」，和系統的 prefers-reduced-motion 是兩件事——後者是無障礙
    #   設定，CSS 那邊無條件遵守，不做成介面上的開關。
    "glow": "breathe",
    "bounds": {"width": 1180, "height": 840},
    # 關閉視窗時要做什麼：ask（每次問）/ tray（縮到背景）/ quit（直接結束）
    "on_close": "ask",
}


def load() -> dict[str, Any]:
    data = dict(DEFAULTS)
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data.update({k: v for k, v in raw.items() if k in DEFAULTS})
    except Exception:
        pass                # 不存在或壞掉都當成「還沒設定過」
    return data


def get(key: str) -> Any:
    return load().get(key, DEFAULTS.get(key))


def set(key: str, value: Any) -> None:        # noqa: A001  和 get 對稱，刻意同名
    if key not in DEFAULTS:
        return              # 不認得的鍵不寫，免得檔案被前端的筆誤養大
    data = load()
    data[key] = value
    try:
        PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError:
        pass                # 寫不進去只是下次回到預設，不值得中斷任何事
