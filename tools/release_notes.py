"""從 commit 生成發版說明。

    python tools/release_notes.py              # 印出來，看過再發
    python tools/release_notes.py --out notes.md
    python tools/release_notes.py --since v1.0.0

⚠ 內容以 `git log <上一個 tag>..HEAD` 為準，不要手打。
⚠ `gh release create` 在遠端建 tag，生成之前要先 `git fetch --tags`。
⚠ 生成之後要讀過再發布。
⚠ `fix` 的 commit body 要寫修正前的行為，工具會原樣帶進說明。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.logger import force_utf8_output      # noqa: E402

# 短雜湊的 commit 連結用，與 core/updater.py 相同。
REPO = "LaiYueTing/scepter-and-sword-assistant"

ROOT = Path(__file__).resolve().parent.parent

# 段落順序就是輸出順序，整理類合成一段。
SECTIONS: list[tuple[str, tuple[str, ...]]] = [
    ("新增（feat）", ("feat",)),
    ("修正（fix）", ("fix",)),
    ("整理（refactor / perf / docs / chore）",
     ("refactor", "perf", "docs", "chore", "style", "test", "build", "ci")),
]

# 「整理」段的標題，`tools` 的修正也歸在這裡
HOUSEKEEPING = next(t for t, _ in SECTIONS if t.startswith("整理"))

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
        # 跳過指向 HEAD 的 tag
        if git("rev-parse", f"{tag}^{{commit}}").strip() != head:
            return tag
    return None


def commits(since: str | None, until: str = "HEAD") -> list[tuple[str, str]]:
    """回傳 [(標題, body)]，舊的在前面。

    ⚠ 發布時指定 `--until <tag>`：HEAD 可能已經超過那個 tag。
    """
    span = f"{since}..{until}" if since else until
    raw = git("log", span, "--reverse", "--no-merges", "--format=%h%x00%s%x00%b%x1e")
    out = []
    for chunk in raw.split("\x1e"):
        if not chunk.strip():
            continue
        sha, subject, body = chunk.strip("\n").split("\x00", 2)
        out.append((sha.strip(), subject.strip(), body.strip()))
    return out


def render(items: list[tuple[str, str, str]]) -> str:
    """把 commit 排成 Markdown，無法辨識格式的歸到整理段，末尾列出這一版涵蓋的 commit。"""
    buckets: dict[str, list[tuple[str, str, bool]]] = {t: [] for t, _ in
                                                       [(s, k) for s, k in SECTIONS]}
    breaking: list[str] = []

    for _sha, subject, body in items:
        m = HEAD_RE.match(subject)
        kind = m.group("type") if m else ""
        text = m.group("text") if m else subject
        scope = (m.group("scope") or "") if m else ""
        if m and m.group("bang"):
            breaking.append(text)

        # 遞增版本號那一筆不進分段，只列在末尾的 commit 對照表。
        if kind == "chore" and scope == "release":
            continue

        # ⚠ `tools/` 不打包進 EXE，這類修正歸到整理段。
        if scope == "tools" and kind in ("fix", "feat", "perf"):
            buckets[HOUSEKEEPING].append(
                (f"{text}（只影響開發，助手本身沒有差別）", body, True))
            continue

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
            # 整理類只寫標題
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

    lines.append("---")
    lines.append("")
    lines.append("### 這一版整合的變更")
    lines.append("")
    # ⚠ 短雜湊寫成 markdown 連結：包在反引號裡的 SHA GitHub 不會自動連結。
    for sha, subject, _body in items:
        lines.append(f"- [`{sha}`](https://github.com/{REPO}/commit/{sha}) {subject}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    force_utf8_output()     # commit 訊息可能含 cp950 沒有的字
    ap = argparse.ArgumentParser(description="從 commit 生成發版說明")
    ap.add_argument("--since", help="從哪個 tag 之後算起（預設是上一個 tag）")
    ap.add_argument("--until", default="HEAD",
                    help="算到哪裡為止（預設 HEAD）。發布時填這一版的 tag，"
                         "免得把還沒發的 commit 也寫進去")
    ap.add_argument("--out", help="寫到檔案，省略就印到終端機")
    args = ap.parse_args()

    since = args.since or previous_tag()
    items = commits(since, args.until)
    if not items:
        print(f"[提醒] {since or '整段歷史'} 之後沒有 commit，沒有東西可以發。")
        return 1

    print(f"[資訊] {since or '第一個 commit'} → {args.until}，"
          f"共 {len(items)} 個 commit", file=sys.stderr)
    text = render(items)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="")
        print(f"[資訊] 已寫入 {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
