"""開發用的進入點：`python -m gui`。

發布版走 `杖劍傳說助手.exe`（雙擊即可），兩條路最後都是 `gui.app.main()`。

⚠ 前端資源要先建置：`cd gui/ui && npm run build`，產物在 `gui/web/`。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import logger   # noqa: E402


def main() -> int:
    # ⚠ 防多開的鎖在 `gui.app.main()` 裡拿，不要在這裡先拿一次——同一個行程拿兩次
    #   會得到 ERROR_ALREADY_EXISTS，變成自己擋住自己。
    try:
        from gui.app import main as app_main
    except ImportError as e:
        logger.message_box(
            "無法開啟圖形介面",
            f"缺少 pywebview：{e}\n\n安裝：python -m pip install pywebview")
        return 1
    return app_main()


if __name__ == "__main__":
    sys.exit(main())
