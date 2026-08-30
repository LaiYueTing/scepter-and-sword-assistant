"""從 commit 生成發版說明。

    python tools/release_notes.py              # 印出來，看過再發
    python tools/release_notes.py --out notes.md
    python tools/release_notes.py --since v1.0.0

版本是**發布**的單位，commit 是**修正**的單位，兩者不必一對一——一個 tag
底下有五個 `fix` 是正常的，而發布頁要把那五個列出來。

⚠ **不要手打發版說明。** 踩過一次：v1.0.1 第一版的說明把 v1.0.0 就有的東西
  寫成這一版的新內容，因為那是憑「這一段工作做過什麼」寫的。從 commit 生成
  的話，那種錯在結構上就不會發生——`git log <上一個 tag>..HEAD` 是唯一的真相。

⚠ **生成之後一定要讀一遍再發。** 這支工具負責「不漏、不多、對得上 commit」，
  而「這條對使用者意味著什麼」仍然是人要判斷的。

⚠ `fix` 的 commit **body 要寫「本來會怎樣」**，工具會原樣帶進說明。只有標題
  的話，發布頁就只有一行「修好 X」，讀的人判斷不出要不要更新。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 段落順序就是輸出順序。整理類的合成一段——使用者看不到的東西不值得各佔一節。
SECTIONS: list[tuple[str, tuple[str, ...]]] = [
    ("新增（feat）", ("feat",)),
    ("修正（fix）", ("fix",)),
    ("整理（refactor / perf / docs / chore）",
     ("refactor", "perf", "docs", "chore", "style", "test", "build", "ci")),
]

# <type>(<scope>)!: <說明>
HEAD_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?: (?P<text>.+)$")


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise SystemExit(f"[錯誤] git {' '.join(args)}：{out.stderr.strip()}")
    return out.stdout


def previous_tag() -> str | None:
    """上一個 tag。沒有 tag 就回 None，那時整段歷史都算這一版。"""
    tags = [t for t in git("tag", "--sort=-creatordate").splitlines() if t.strip()]
    head = git("rev-parse", "HEAD").strip()
    for tag in tags:
        # 跳過指向 HEAD 的那個——它就是這一版自己的 tag
        if git("rev-parse", f"{tag}^{{commit}}").strip() != head:
            return tag
    return None


def commits(since: str | None) -> list[tuple[str, str]]:
    """回傳 [(標題, body)]，舊的在前面（讀起來才是發生順序）。"""
    span = f"{since}..HEAD" if since else "HEAD"
    raw = git("log", span, "--reverse", "--no-merges", "--format=%H%x00%s%x00%b%x1e")
    out = []
    for chunk in raw.split("\x1e"):
        if not chunk.strip():
            continue
        _, subject, body = chunk.strip("\n").split("\x00", 2)
        out.append((subject.strip(), body.strip()))
    return out


def render(items: list[tuple[str, str]]) -> str:
    """把 commit 排成 Markdown。認不得格式的一律歸到整理那段，不要吞掉。"""
    buckets: dict[str, list[tuple[str, str, bool]]] = {t: [] for t, _ in
                                                       [(s, k) for s, k in SECTIONS]}
    breaking: list[str] = []

    for subject, body in items:
        m = HEAD_RE.match(subject)
        kind = m.group("type") if m else ""
        text = m.group("text") if m else subject
        scope = (m.group("scope") or "") if m else ""
        if m and m.group("bang"):
            breaking.append(text)

        for title, kinds in SECTIONS:
            if kind in kinds or (not m and kinds[0] == "refactor"):
                buckets[title].append((text, body, bool(scope)))
                break

    lines: list[str] = []
    if breaking:
        lines.append("## ⚠ 不相容的變更")
        lines.append("")
        for text in breaking:
            lines.append(f"- {text}")
        lines.append("")

    for title, _ in SECTIONS:
        got = buckets[title]
        if not got:
            continue
        lines.append(f"## {title}")
        lines.append("")
        if title.startswith("整理"):
            # 整理類只寫結果，不逐條展開 body——那些是給讀程式碼的人看的
            for text, _body, _ in got:
                lines.append(f"- {text}")
            lines.append("")
            continue
        for text, body, _ in got:
            lines.append(f"**{text}**")
            lines.append("")
            if body:
                lines.append(body)
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="從 commit 生成發版說明")
    ap.add_argument("--since", help="從哪個 tag 之後算起（預設是上一個 tag）")
    ap.add_argument("--out", help="寫到檔案，省略就印到終端機")
    args = ap.parse_args()

    since = args.since or previous_tag()
    items = commits(since)
    if not items:
        print(f"[提醒] {since or '整段歷史'} 之後沒有 commit，沒有東西可以發。")
        return 1

    print(f"[資訊] 從 {since or '第一個 commit'} 起算，共 {len(items)} 個 commit",
          file=sys.stderr)
    text = render(items)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="")
        print(f"[資訊] 已寫入 {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
