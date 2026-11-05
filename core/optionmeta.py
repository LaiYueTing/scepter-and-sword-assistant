"""開關與腳本的中文對照表：標籤、補充說明、歸屬的腳本、數值範圍。

⚠ 不 import 任何介面框架，測試與命令列也會讀這份表。
⚠ 標籤與說明和 config.example.yaml 的註解重複，改開關的語意時兩邊都要改。
"""

from __future__ import annotations

def task_label(name: str) -> str:
    """腳本的中文名，取自腳本的 `name:`，讀不到就用原名。"""
    from core.engine import Script

    try:
        return Script.load(name, {}).name
    except Exception:
        return name


# 開關 → (標籤, 補充說明)。
#
# 說明的格式：先講它做什麼，再講關閉或填別的值會怎樣；沒有補充就留空字串。
# ⚠ 這是介面文案，不寫日期、演進過程與實測來源。
OPTION_LABELS: dict[str, tuple[str, str]] = {
    "claim_reward": ("評級 S 就領獎", "關閉後一律不領獎，結束後直接退出，可以持續累積友情點數"),
    "stop_when_no_count": ("領獎次數用完就結束本輪", "關閉後會繼續打，搭配上一項用於刷友情點數"),
    "buy_counts": ("次數用完時用晨星補買幾次", "遊戲每日限購 2 次。填 0 表示不購買"),
    "claim_rank_a_after": ("打幾場都拿不到 S 就改領 A", "同一輪連續這麼多場沒有 S，之後結算是 A 也領獎。填 0 表示不啟用，一直打到 S 為止"),
    "stock_up_before_new_dungeon": (
        "新副本開放前一天先囤領獎次數",
        "當天不領取舊副本的獎勵（達成 S 也不領）、用晨星把次數買滿、只打一場就結束本輪，把次數全部保留到隔天在新副本上使用。"
        "預設關閉，因為會消耗晨星"),
    "accept_with_partners": ("配對補了 NPC 夥伴也接受", "關閉後只接受真人隊伍。深夜時段通常人數不足，可能整晚無法進行"),
    "auto_battle_mode": ("進入戰鬥後開啟自動模式", "包含自動準備與自動治療"),
    "like_teammates": ("結算頁替隊友按讚", ""),
    "claim_raid_reward": ("討伐獎勵可領取時立即領走", ""),
    "wait_for_others": ("等場上有人開打後才入場", "關閉後一到可挑戰的樓層就進入。過早進場會被踢出戰場"),
    "claim_daily_reward": ("完成後領取每日活動的獎勵", "關閉後只刷成績不領獎，當天之內仍可手動領取"),
    "daily_dual_records": ("領取雙影幻境的擊破紀錄獎勵", "排行榜有驚嘆號時，到歷戰紀錄領走達成波次的獎勵"),
    "crush_arena": ("使用競技場券進行排位戰", "關閉後只在週一按下開啟挑戰，不進行對戰"),
    "arena_opponent": ("挑戰第幾位對手", "1 為戰力最高，排名上升較快但可能落敗；4 必定為碾壓，不會失敗但也不增加排名"),
    "arena_max_battles": ("每日最多進行幾場", "券的上限為 20，填 20 等於有券就全部使用。落敗的場次同樣計入"),
    "arena_monday_use_all": ("週一不限場次，有券就全部使用", "新一期從週一開始，早一點往前爬排名會比較前面。其他天照每日場次上限"),
    "arena_retry_on_loss": ("落敗後更換對手再次挑戰", "落敗後改挑排名低一階的對手，連續三場落敗即結束本輪，剩餘的券保留至下次"),
    "arena_opponent_2": ("落敗一場後改挑第幾位", "預設為 2，也就是往右一格"),
    "arena_opponent_3": ("落敗兩場後改挑第幾位", "預設為 3，也就是再往右一格"),
    "buy_arena_tickets": ("券用完時用晨星補買", "每張 10 晨星，每日限購 8 張。預設關閉"),
    "chores_shop": ("領取商城的巡禮之證與免費贈禮", "巡禮之證的巡禮目標與巡禮指引獎勵，以及「每日優惠」「本週精選」左上角的每日贈禮與每週贈禮"),
    "chores_friends": ("領取友情幣", "好友頁底部的友情幣，有驚嘆號時開啟並領取"),
    "chores_tasks": ("領取任務獎勵", "日常任務可領的全部領取，週常有驚嘆號時也切過去領取"),
    "chores_rewards": ("領取餽贈", "功能區的「餽贈」，按一次領取就會全部領走"),
    "chores_treasure": ("領取祕寶大作戰的能量", "精彩活動的祕寶大作戰，「獲得能量」裡可領的全部領取"),
    "chores_signin": ("每日簽到", "精彩活動的每日簽到，領取當天的獎勵"),
    "chores_fruit": ("領取命運果實", "地圖探索頁的卡片顯示「可領取」時直接點擊領取，不需進入果實頁面"),
    "chores_bond": ("執行羈絆冒險", "進入地圖上標示紅色驚嘆號的節點領取獎勵或派遣（快速選擇後直接委派）"),
    "chores_material": ("素材祕境一鍵購買", "會花晨星，預設關閉。讀出每列今天已買幾組，只補到下面設定的組數，手動買過的也算進去"),
    "material_hammer_sets": ("鐵鎚每天最多買幾組", "鐵石礦洞用。填 0 不買，最多 20。組數越多單價越高"),
    "material_pickaxe_sets": ("十字鎬每天最多買幾組", "黃金礦洞用。填 0 不買，最多 20"),
    "material_glove_sets": ("拳套每天最多買幾組", "怪物洞窟用。填 0 不買，最多 20"),
    "material_shovel_sets": ("鏟子每天最多買幾組", "砂石礦洞用。填 0 不買，最多 20"),
    "chores_donate": ("執行公會捐獻", "前往公會大廳的「公會捐贈」，完成每日 5 次捐獻。關閉後這一趟只執行上面幾段，完成即結束本輪"),
    "guild_donate_free": ("免費的那一次", "每日第一次免費"),
    "guild_donate_stars": ("免費之後用晨星繼續捐", "價格逐次遞增。晨星同時也是競技場購券、副本購買次數的來源"),
    "guild_donate_star_times": ("最多再用晨星捐幾次", "每日合計 5 次，填 4 即為捐滿。此上限跨執行保留，補跑不會重新計數"),

    # 討伐的等人策略。人數換算成順序條的單位數，誤差約 ±2～3 人。
    "raid_join_players": ("估計到幾人在打就入場", "同樣消耗一次次數。人數多的場次存活時間長，造成的傷害高出數倍"),
    "raid_join_wait_minutes": ("等待幾分鐘仍不足人數就跟著入場", "保底機制。進入房間等待這麼久仍未達上述人數時，有人就跟著入場，不等到結束本輪"),
    "raid_plateau_players": ("人數停在幾人不再增加就入場", "用於當日達不到 10 人的情況。人數仍在上升時不會成立"),
    "raid_plateau_sustain": ("停留幾秒視為不再增加", "設得太短會在人數仍在上升時就入場"),
    "raid_page_wait_minutes": ("討伐頁無人挑戰時，等幾分鐘就自行開場", "自進入討伐頁起算。這段時間是保留給公會成員陸續上線的"),
    "raid_solo_after_minutes": ("房間內無人開打時，等幾分鐘就自行開打", "按鈕顯示「開始戰鬥」代表尚無人真正開打。單人的效益極差，這是最後手段。要填 10 以下：旁觀滿 10 分鐘會被踢回討伐頁"),
    "raid_page_giveup_minutes": ("在討伐頁停留幾分鐘就放棄", "安全網，會保存一張截圖。⚠ 必須大於上面的「自行開場」分鐘數"),

    "rift_heal_with_food": ("隊伍被打倒時用料理治療，繼續打", "遊戲會問「要使用料理治療嗎」。關閉時停在那個框結束本輪，由你決定"),
}

# 這幾個是上一個開關的子項目。
# ⚠ 縮排由畫面的 padding 處理，不要寫進標籤字串。
SUB_OPTIONS = {
    "guild_donate_free",
    "guild_donate_stars",
    "guild_donate_star_times",
    "material_hammer_sets",
    "material_pickaxe_sets",
    "material_glove_sets",
    "material_shovel_sets",
    "raid_plateau_sustain",
}

# 開關屬於哪一份腳本，左邊是腳本名（中文名由 task_label() 取得）。
#
# ⚠ 新增開關時要同時登記在這裡和 OPTION_LABELS，否則介面會顯示原始鍵名並歸到「其他」。
#   tests/test_options_complete.py 會檢查。
OPTION_GROUPS = [
    ("dungeon", ["claim_reward", "stop_when_no_count", "buy_counts", "claim_rank_a_after",
                 "stock_up_before_new_dungeon",
                 "accept_with_partners", "auto_battle_mode", "like_teammates"]),
    ("raid", ["claim_raid_reward", "wait_for_others",
              "raid_join_players", "raid_join_wait_minutes",
              "raid_plateau_players", "raid_plateau_sustain",
              "raid_page_wait_minutes", "raid_solo_after_minutes",
              "raid_page_giveup_minutes"]),
    ("daily", ["claim_daily_reward", "daily_dual_records"]),
    ("arena", ["crush_arena", "arena_max_battles", "arena_monday_use_all",
               "arena_opponent",
               "arena_retry_on_loss", "arena_opponent_2",
               "arena_opponent_3", "buy_arena_tickets"]),
    ("chores", ["chores_shop", "chores_friends", "chores_tasks", "chores_rewards",
                "chores_treasure", "chores_signin",
                "chores_fruit", "chores_bond",
                "chores_material", "material_hammer_sets", "material_pickaxe_sets",
                "material_glove_sets", "material_shovel_sets",
                "chores_donate",
                "guild_donate_free", "guild_donate_stars",
                "guild_donate_star_times"]),
    ("rift", ["rift_heal_with_food"]),
]

# 數值欄位的範圍與單位。key: (最小, 最大, 單位, 小數位)
#
# ⚠ 小數位不可省略：raid_plateau_players 預設 6.5，整數欄位會寫回 6。
OPTION_RANGES: dict[str, tuple[float, float, str, int]] = {
    "arena_max_battles": (1, 30, "", 0),
    "arena_opponent": (1, 4, "", 0),
    "arena_opponent_2": (1, 4, "", 0),
    "arena_opponent_3": (1, 4, "", 0),
    "buy_counts": (0, 2, "", 0),
    "claim_rank_a_after": (0, 30, "", 0),
    "guild_donate_star_times": (0, 4, "", 0),
    "material_hammer_sets": (0, 20, "", 0),
    "material_pickaxe_sets": (0, 20, "", 0),
    "material_glove_sets": (0, 20, "", 0),
    "material_shovel_sets": (0, 20, "", 0),
    "raid_join_players": (1, 30, "", 0),
    "raid_join_wait_minutes": (1, 60, "", 0),
    "raid_plateau_players": (1, 30, "", 1),
    "raid_plateau_sustain": (10, 600, "", 0),
    "raid_page_wait_minutes": (1, 60, "", 0),
    "raid_solo_after_minutes": (1, 9, "", 0),
    "raid_page_giveup_minutes": (1, 90, "", 0),
}

# 每份腳本「次數」的意思
REPEAT_HINTS = {
    "dungeon": "一輪要打幾場副本。0 = 不限，打到次數用盡自己結束本輪（建議）",
    "daily": "雙影幻境最多打幾場。推到 12 波就會提早結束本輪，所以平常只會用掉 1 場",
    "raid": "一輪要參加幾場討伐。討伐每天只有 2 次，通常填 1",
}
