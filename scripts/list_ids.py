"""列出所有内容 id，方便填 data/curated.json 的置顶 / 隐藏配置。

用法：
    python scripts/list_ids.py                  # 视频
    python scripts/list_ids.py --type audio
    python scripts/list_ids.py --type project
    python scripts/list_ids.py --grep 吴语       # 按关键词过滤
    python scripts/list_ids.py --type video --limit 40
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SNAPSHOT = os.path.join(ROOT, "data", "snapshot.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default="video",
                    choices=["video", "audio", "project", "post", "all"])
    ap.add_argument("--grep", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pinned-only", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(SNAPSHOT):
        print("找不到快照：%s\n请先运行 collect_all.py" % SNAPSHOT)
        return 1
    snap = json.load(open(SNAPSHOT, "r", encoding="utf-8"))

    rows = [i for i in snap.get("items") or []
            if (args.type == "all" or i["type"] == args.type)
            and (not args.grep or args.grep in (i.get("title") or ""))
            and (not args.pinned_only or i.get("pinned"))]
    rows.sort(key=lambda i: i.get("publishedAt") or "", reverse=True)
    if args.limit:
        rows = rows[:args.limit]

    print("共 %d 条（type=%s%s）\n" % (len(rows), args.type,
                                    "，关键词=%s" % args.grep if args.grep else ""))
    for i in rows:
        flag = " [置顶]" if i.get("pinned") else ""
        print("%-34s %s  %s%s" % (
            i["id"], (i.get("publishedAt") or "----------")[:10],
            (i.get("title") or "")[:44], flag))

    print("\n把上面的 id 粘进 data/curated.json 的 featured（加进精选项目）或 hidden（不上站）即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
