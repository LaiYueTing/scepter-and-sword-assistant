"""六份腳本共用的開機與後備規則，每一份都要有。

漏掉一份不會有任何錯誤訊息：那份腳本只是在某張畫面上沒有規則認得，掉進後備規則
空按返回鍵，紀錄上看不出是少了一條規則。

selftest 驗不到：它問的是「這張畫面該觸發哪條規則」，而少一條規則時它只會去驗
別的樣本——沒有樣本的那張畫面，沒有人會問起。
"""
import os
import tempfile
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# ⚠ 測試不能寫進真正的 assistant.log，要在 import core 之前設定。
os.environ.setdefault("SSA_LOG_DIR", tempfile.mkdtemp(prefix="ssa-test-log-"))

import yaml

SCRIPTS = ("dungeon", "raid", "daily", "arena", "chores", "rift")

# 這些規則和腳本要做什麼完全無關——它們處理的是「進不進得去遊戲」與「卡住了
# 怎麼辦」，所以每一份都要有。腳本各自的流程規則（配對、領獎、導覽）不在此列。
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

# 這一條在該份腳本裡刻意不同：虛空裂縫要從使用者自己組好隊伍的活動地圖開始，
# 停在家園代表沒得做，「回家園重來」對它沒有意義——它改成「家園 → 結束本輪」兩條。
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

# ⚠ 後備規則鏈最後兩條的 absent 必須**完全一樣**。少列任何一個，重新啟動遊戲那條就會在
#   那個畫面上誤觸發——而重新啟動一次要 152 秒。
for name in SCRIPTS:
    back = rules[name]["完全無法辨識 → 按系統返回鍵"]
    restart = rules[name]["持續無法脫困 → 重新啟動遊戲"]
    check(f"{name}：重新啟動遊戲那條的 absent 和上一條一樣",
          set(back.get("absent") or []) == set(restart.get("absent") or []))
    # ⚠ 上一條一定要有 max_fires，否則它每輪都成立、永遠輪不到重新啟動那條。
    check(f"{name}：按返回鍵那條有 max_fires", bool(back.get("max_fires")))
    check(f"{name}：重新啟動遊戲那條有 max_fires", bool(restart.get("max_fires")))

    # ⚠ 標題畫面的重新啟動要把點擊次數歸零，否則重新啟動後正常的標題畫面會直接被當成
    #   「點了仍沒有反應」而結束本輪。
    title = rules[name]["標題畫面 → 點擊開始遊戲"]
    title_restart = rules[name]["標題畫面點了沒有反應 → 重新啟動遊戲"]
    resets = [a.get("reset_fires") for a in title_restart.get("do") or [] if "reset_fires" in a]
    check(f"{name}：標題畫面點擊有 max_fires", bool(title.get("max_fires")))
    check(f"{name}：標題畫面重新啟動會把點擊次數歸零",
          any("標題畫面 → 點擊開始遊戲" in (r if isinstance(r, list) else [r]) for r in resets))

print()
print("全部通過" if ok else "有項目失敗")
sys.exit(0 if ok else 1)
