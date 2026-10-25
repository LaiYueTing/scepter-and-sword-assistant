"""產生 templates/search_regions.yaml：固定 UI 元素的預設搜尋範圍。

    python tools/gen_search_regions.py [額外的截圖資料夾 ...]

做法：每個模板在 samples/（與額外給的資料夾）裡全畫面比對，分數 ≥0.75 的位置取外框，
再往四邊外擴 MARGIN。產生之後逐張驗證「限定範圍找到的」與「全畫面找到的」完全一致，
不一致的模板不寫進表裡。

⚠ 只處理固定在 UI 上的元素。會隨捲動、鏡頭或版面移動的內容（公會島建築、羈絆地圖
  記號、副本列表卡片、難度頁籤）與多個對話框共用的按鈕（確定、取消）列在 EXCLUDE，
  它們出現的位置不受樣本限制。
⚠ 新增模板或補了樣本之後重新執行一次。表上沒有的模板照舊掃全畫面，不會出錯，只是慢。
"""
from __future__ import annotations

import glob
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from core import vision   # noqa: E402

MARGIN = 100          # 外擴的像素，涵蓋提示文字把元素往下推之類的版面位移
MIN_SCORE = 0.75      # 低於所有規則門檻（最低 0.78），比對成功的位置都算進來
MAX_AREA = 0.45       # 範圍超過整個畫面的這個比例就不值得限定
W, H = 720, 1280

EXCLUDE = {
    # 隨鏡頭或捲動移動
    "building_raid_gate", "building_raid_gate_night", "building_guild_hall",
    "mark_bond_node", "mark_bond_ready", "label_fruit_ready",
    "label_unlock_countdown", "label_max_rank_text", "label_no_rank_text",
    "label_countdown_days", "card_daily_dungeon",
    # 右側圖示列：上方多一個「限時禮包」之類的圖示就整排往下推
    "label_rift_widget", "label_rift_zero",
    # 一列中的多個位置，靠 pick 或 tap_all 選
    "tab_lock", "tab_selected", "tab_inferno_on", "btn_arena_fight", "btn_like",
    "slot_empty", "reward_dot", "reward_claimed", "reward_available",
    # 多個對話框共用的按鈕，位置隨對話框不同
    "btn_confirm", "btn_cancel", "btn_add_count", "btn_slider_plus",
    "btn_purchase_confirm", "btn_buy_max", "btn_buy_ticket", "btn_heal_all",
    "btn_reject", "btn_material_buy", "btn_quick_select",
}


def images(extra: list[str]) -> list[tuple[str, object]]:
    files = sorted(glob.glob("samples/*.png")) + sorted(glob.glob("samples/ocr/*.png"))
    for folder in extra:
        files += sorted(glob.glob(os.path.join(folder, "**", "*.png"), recursive=True))
    out = []
    for f in files:
        img = vision.imread_unicode(f)
        if img.shape[:2] == (H, W):
            out.append((f, img))
    return out


def best(img, tpl, region=None):
    area, ox, oy = vision._crop(img, region)
    th, tw = tpl.shape[:2]
    if area.shape[0] < th or area.shape[1] < tw:
        return -1.0, None
    r = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(r)
    return float(mx), (loc[0] + ox, loc[1] + oy)


def measure(name: str, imgs) -> list[int] | None:
    """量一個模板的範圍並驗證；不適合限定範圍就回傳 None。"""
    tpl = vision.load_template(name)
    th, tw = tpl.shape[:2]
    full = [best(img, tpl) for _, img in imgs]
    hits = [loc for score, loc in full if score >= MIN_SCORE]
    if not hits:
        return None
    x0 = max(0, min(x for x, _ in hits) - MARGIN)
    y0 = max(0, min(y for _, y in hits) - MARGIN)
    x1 = min(W, max(x for x, _ in hits) + tw + MARGIN)
    y1 = min(H, max(y for _, y in hits) + th + MARGIN)
    region = [x0, y0, x1 - x0, y1 - y0]
    if region[2] * region[3] > MAX_AREA * W * H:
        return None
    # 驗證：全畫面能比對到的，限定範圍也要在同一個位置找到同樣的分數。
    bad = []
    for (f, img), (full_score, full_loc) in zip(imgs, full):
        if full_score < MIN_SCORE:
            continue
        hint_score, hint_loc = best(img, tpl, tuple(region))
        # 範圍大小不同時 OpenCV 可能改用 FFT 計算，同一位置的分數會有 1e-5 級的誤差。
        moved = hint_loc is None or max(abs(hint_loc[0] - full_loc[0]),
                                        abs(hint_loc[1] - full_loc[1])) > 2
        if moved or abs(hint_score - full_score) > 1e-3:
            bad.append(os.path.basename(f))
    if bad:
        print(f"  略過 {name}：{len(bad)} 張不一致（{bad[0]} 等）")
        return None
    return region


def main() -> int:
    imgs = images(sys.argv[1:])
    print(f"驗證畫面 {len(imgs)} 張")
    names = [Path(p).stem for p in sorted(glob.glob("templates/*.png"))]
    names = [n for n in names if n not in EXCLUDE]
    cv2.setNumThreads(1)        # 平行處理在模板這一層，OpenCV 自己不要再開執行緒
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        results = list(pool.map(lambda n: measure(n, imgs), names))
    regions = {name: region for name, region in zip(names, results) if region}

    out = ROOT / "templates" / "search_regions.yaml"
    lines = ["# 固定 UI 元素的預設搜尋範圍 [x, y, w, h]，由 tools/gen_search_regions.py 產生。",
             "# 不要手改：補了樣本或新增模板後重新執行那支工具。", ""]
    lines += [f"{name}: [{', '.join(map(str, r))}]" for name, r in sorted(regions.items())]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    saved = sum(1 - r[2] * r[3] / (W * H) for r in regions.values()) / max(1, len(regions))
    print(f"寫入 {len(regions)} 個模板的範圍：{out}（平均少掃 {saved:.0%} 的面積）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
