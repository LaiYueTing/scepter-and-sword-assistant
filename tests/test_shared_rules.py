"""七份腳本共用的開機與後備規則，每一份都要有。"""
import os
import tempfile
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# ⚠ 測試不寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import yaml

SCRIPTS = ("dungeon", "raid", "daily", "arena", "chores", "rift", "chaos")

# 處理進入遊戲與脫困的規則。腳本各自的流程規則不在此列。
SHARED = [
    "伺服器維護中 → 結束本輪，下一輪再試",
    "遊戲要求重新進入 → 重新啟動遊戲",
    "重新啟動後仍要求重新進入 → 結束本輪，下一輪再試",
    "帳號在其他用戶端登入 → 按確定回到登入畫面",
    "公告 → 勾選今日不再提醒後關閉",
    "標題畫面 → 點擊開始遊戲",
    "標題畫面點了沒有反應 → 重新啟動遊戲",
    "重新啟動後仍停在標題畫面 → 結束本輪",
    "遊戲啟動中 → 等開場動畫",
    "遊戲啟動中 → 等載入完成",
    "載入中 → 等畫面切換",
    "限時禮包對話框 → 按系統返回鍵關閉",
    "觀戰確認框 → 確定退出",
    "退出確認對話框 → 確定退出",
    "點空白處無法關閉的頁面 → 重新啟動遊戲",
    "重新啟動後仍無法關閉 → 結束本輪",
    "誤入次要頁面 → 點返回退出",
    "停在無法處理的畫面 → 回家園重新開始",
    "完全無法辨識 → 按系統返回鍵",
    "持續無法脫困 → 重新啟動遊戲",
    "重新啟動遊戲也無法恢復 → 結束本輪",
]

# 虛空裂縫從活動地圖開始，停在家園就結束本輪，不需要這一條。
EXEMPT = {"rift": {"停在無法處理的畫面 → 回家園重新開始"}}

ok = True


def check(label, cond):
    global ok
    print(("[通過] " if cond else "[失敗] ") + label)
    ok = ok and bool(cond)


rules = {}
for name in SCRIPTS:
    raw = yaml.safe_load(pathlib.Path(f"scripts/{name}.yaml").read_text(encoding="utf-8"))
    rules[name] = {r["name"]: r for r in raw["rules"]}

for shared in SHARED:
    missing = [n for n in SCRIPTS
               if shared not in rules[n] and shared not in EXEMPT.get(n, ())]
    check(f"每份腳本都有「{shared}」", not missing)
    if missing:
        print("       缺：" + "、".join(missing))

# 後備規則鏈最後兩條的 absent 必須完全相同。
for name in SCRIPTS:
    back = rules[name]["完全無法辨識 → 按系統返回鍵"]
    restart = rules[name]["持續無法脫困 → 重新啟動遊戲"]
    check(f"{name}：重新啟動遊戲那條的 absent 和上一條一樣",
          set(back.get("absent") or []) == set(restart.get("absent") or []))
    # 上一條要有 max_fires，否則輪不到重新啟動那條。
    check(f"{name}：按返回鍵那條有 max_fires", bool(back.get("max_fires")))
    check(f"{name}：重新啟動遊戲那條有 max_fires", bool(restart.get("max_fires")))

    # 標題畫面的重新啟動要把點擊次數歸零。
    title = rules[name]["標題畫面 → 點擊開始遊戲"]
    title_restart = rules[name]["標題畫面點了沒有反應 → 重新啟動遊戲"]
    resets = [a.get("reset_fires") for a in title_restart.get("do") or [] if "reset_fires" in a]
    check(f"{name}：標題畫面點擊有 max_fires", bool(title.get("max_fires")))
    check(f"{name}：標題畫面重新啟動會把點擊次數歸零",
          any("標題畫面 → 點擊開始遊戲" in (r if isinstance(r, list) else [r]) for r in resets))

print()
print("全部通過" if ok else "有項目失敗")
sys.exit(0 if ok else 1)
