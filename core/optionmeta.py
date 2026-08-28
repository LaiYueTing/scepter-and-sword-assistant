"""開關與腳本的中文對照表：標籤、補充說明、歸屬的腳本、數值範圍。

⚠ **這裡不 import 任何介面框架。** 對照表是**資料**，介面只是拿它去畫；混進
  框架之後，任何想讀這份表的地方（測試、命令列）都得先把整套介面
  載進來。抄成兩份則會有不一致的那天，這個專案已經在改名時現形過一次。

⚠ 開關的中文標籤與說明在這裡各留一份，和 config.example.yaml 的註解是重複的。
  這是刻意的取捨：註解要教人怎麼填、可以寫很長，介面只放得下一兩行。改開關的
  語意時兩邊都要動。
"""

from __future__ import annotations

def task_label(name: str) -> str:
    """腳本的中文名，直接取自腳本的 `name:`，讀不到就用原名。

    ⚠ 不另外維護一份對照表。紀錄那邊（`Runner._title`）就是這樣取的，
      兩份各寫一次的話，改了名字而漏掉其中一份的那天不會有人發現。
    """
    from core.engine import Script

    try:
        return Script.load(name, {}).name
    except Exception:
        return name


# 開關 → (標籤, 補充說明)。
#
# 說明的形狀固定：**先講它做什麼，再講關掉／填別的值會怎樣**——後者才是使用者猶豫
# 的點。沒有補充可講就留空字串，不要為了湊格式硬寫一句。
#
# ⚠ 這是**介面上的文案**，不是開發筆記。不寫日期、不寫「原本 X 後來改成 Y」、
#   不寫實測數字的來源——那些寫在 CLAUDE.md 裡。
OPTION_LABELS: dict[str, tuple[str, str]] = {
    "claim_reward": ("評級 S 就領獎", "關閉後一律不領獎，打完就退出，可以持續刷友情點數"),
    "stop_when_no_count": ("領獎次數用完就收工", "關閉後會繼續打，搭配上一項用於刷友情點數"),
    "buy_counts": ("次數用完時用晨星補買幾次", "遊戲每日限購 2 次。填 0 表示不購買"),
    "stock_up_before_new_dungeon": (
        "新副本開放前一天先囤領獎次數",
        "當天不領取舊副本的獎勵（達成 S 也不領）、用晨星把次數買滿、只打一場就收工，把次數全部保留到隔天在新副本上使用。"
        "預設關閉，因為會消耗晨星"),
    "accept_with_partners": ("配對湊了 NPC 夥伴也接受", "關閉後只接受真人隊伍。深夜時段通常湊不齊，可能整晚無法進行"),
    "auto_battle_mode": ("進入戰鬥後開啟自動模式", "包含自動準備與自動治療"),
    "like_teammates": ("結算頁替隊友按讚", ""),
    "claim_raid_reward": ("討伐獎勵可領取時立即領走", ""),
    "wait_for_others": ("等場上有人開打後才入場", "關閉後一到可挑戰的樓層就進入。過早進場會被踢出戰場"),
    "claim_daily_reward": ("完成後領取每日活動的獎勵", "關閉後只刷成績不領獎，當天之內仍可手動領取"),
    "crush_arena": ("使用競技場券進行排位戰", "關閉後只在週一按下開啟挑戰，不進行對戰"),
    "arena_opponent": ("挑戰第幾位對手", "1 為戰力最高，排名上升較快但可能落敗；4 必定為碾壓，不會失敗但也不增加排名"),
    "arena_max_battles": ("每日最多進行幾場", "券的上限為 20，填 20 等於有券就打完。落敗的場次同樣計入"),
    "arena_retry_on_loss": ("落敗後更換對手再次挑戰", "落敗後改挑排名低一階的對手，連續三場落敗即收工，剩餘的券保留至下次"),
    "arena_opponent_2": ("落敗一場後改挑第幾位", "預設為 2，也就是往右一格"),
    "arena_opponent_3": ("落敗兩場後改挑第幾位", "預設為 3，也就是再往右一格"),
    "buy_arena_tickets": ("券用完時用晨星補買", "每張 10 晨星，每日限購 8 張。預設關閉"),
    "chores_fruit": ("領取命運果實", "地圖探索頁的卡片顯示「可領取」時直接點掉，不需進入果實頁面"),
    "chores_bond": ("執行羈絆冒險", "進入地圖上標示紅色驚嘆號的節點領取獎勵或派遣（快速選擇後直接委派）"),
    "chores_donate": ("執行公會捐獻", "前往公會大廳的「公會捐贈」，完成每日 5 次捐獻。關閉後這一趟只執行上面兩段，完成即收工"),
    "guild_donate_free": ("免費的那一次", "每日第一次免費"),
    "guild_donate_stars": ("免費之後用晨星繼續捐", "價格逐次遞增。晨星同時也是競技場購券、副本購買次數的來源"),
    "guild_donate_star_times": ("最多再用晨星捐幾次", "每日合計 5 次，填 4 即為捐滿。此上限跨執行保留，補跑不會重新計數"),

    # 討伐的等人策略。人數會照校準過的換算式換成順序條的單位數，誤差約 ±2～3 人。
    "raid_join_players": ("估計到幾人在打就入場", "同樣消耗一次次數。人數多的場次存活時間長，造成的傷害高出數倍"),
    "raid_join_wait_minutes": ("等待幾分鐘仍不足人數就跟著打", "保底機制。進入房間等待這麼久仍湊不到上述人數時，有人就跟著打，不空等到收工"),
    "raid_plateau_players": ("人數停在幾人不再增加就入場", "用於接住「今日湊不到 10 人」的情況。人數仍在上升時不會成立"),
    "raid_plateau_sustain": ("停留幾秒視為不再增加", "設得太短會在人數仍在上升時就入場"),
    "raid_page_wait_minutes": ("討伐頁無人挑戰時，等幾分鐘就自行開場", "自進入討伐頁起算。這段時間是保留給公會成員陸續上線的"),
    "raid_solo_after_minutes": ("房間內無人開打時，等幾分鐘就自行開打", "按鈕顯示「開始戰鬥」代表尚無人真正開打。單人的效益極差，這是最後手段"),
    "raid_page_giveup_minutes": ("在討伐頁停留幾分鐘就放棄", "安全網，會保存一張截圖。⚠ 必須大於上面的「自行開場」分鐘數"),
}

# 這幾個是上一個開關的子項目（爸爸關掉，它們就沒有意義）。
#
# ⚠ **縮排是排版，不要寫進標籤字串裡。** 原本是在標籤前面塞「　└ 」，那是等寬
#   主控台的思維——比例字型加上 grid 版面就對不齊，而且「說明文字要縮多少」完全
#   無從得知。改成資料之後，畫面那邊用真正的縮排去排。
SUB_OPTIONS = {
    "guild_donate_free",
    "guild_donate_stars",
    "guild_donate_star_times",
    "raid_plateau_sustain",
}

# 這些開關屬於哪一份腳本。左邊是**腳本名**不是中文名——中文名由 task_label()
# 去腳本的 `name:` 拿，維護兩份就會有不一致的那天（改名時已經現形過一次）。
#
# ⚠ 新增開關時一定要同時登記在這裡和 OPTION_LABELS，漏掉的話介面上會顯示原始
#   鍵名並掉進「其他」分頁。檢查法：
#       grouped = {k for _, ks in OPTION_GROUPS for k in ks}
#       [k for k in options if k not in grouped or k not in OPTION_LABELS]
OPTION_GROUPS = [
    ("dungeon", ["claim_reward", "stop_when_no_count", "buy_counts",
                 "stock_up_before_new_dungeon",
                 "accept_with_partners", "auto_battle_mode", "like_teammates"]),
    ("raid", ["claim_raid_reward", "wait_for_others",
              "raid_join_players", "raid_join_wait_minutes",
              "raid_plateau_players", "raid_plateau_sustain",
              "raid_page_wait_minutes", "raid_solo_after_minutes",
              "raid_page_giveup_minutes"]),
    ("daily", ["claim_daily_reward"]),
    ("arena", ["crush_arena", "arena_max_battles", "arena_opponent",
               "arena_retry_on_loss", "arena_opponent_2",
               "arena_opponent_3", "buy_arena_tickets"]),
    ("chores", ["chores_fruit", "chores_bond", "chores_donate",
                "guild_donate_free", "guild_donate_stars",
                "guild_donate_star_times"]),
]

# 數值欄位的範圍與單位。key: (最小, 最大, 單位, 小數位)
#
# ⚠ 小數位是必要的：raid_plateau_players 預設 6.5，用整數欄位會被無聲地寫回 6，
#   使用者只是打開介面看一眼，門檻就被改掉了。
OPTION_RANGES: dict[str, tuple[float, float, str, int]] = {
    "arena_max_battles": (1, 30, "", 0),
    "arena_opponent": (1, 4, "", 0),
    "arena_opponent_2": (1, 4, "", 0),
    "arena_opponent_3": (1, 4, "", 0),
    "buy_counts": (0, 2, "", 0),
    "guild_donate_star_times": (0, 4, "", 0),
    "raid_join_players": (1, 30, "", 0),
    "raid_join_wait_minutes": (1, 60, "", 0),
    "raid_plateau_players": (1, 30, "", 1),
    "raid_plateau_sustain": (10, 600, "", 0),
    "raid_page_wait_minutes": (1, 60, "", 0),
    "raid_solo_after_minutes": (1, 60, "", 0),
    "raid_page_giveup_minutes": (1, 90, "", 0),
}

# 每份腳本的「次數」各有各的意思，只寫一個數字看不出來
REPEAT_HINTS = {
    "dungeon": "一輪要打幾場副本。0 = 不限，打到次數用盡自己收工（建議）",
    "daily": "雙影幻境最多打幾場。推到 12 波就會提早收工，所以平常只會用掉 1 場",
    "raid": "一輪要參加幾場討伐。討伐每天只有 2 次，通常填 1",
}
