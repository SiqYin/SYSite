"""采集编排入口。

用法：
    python scripts/collect_all.py            # 正常抓取（带缓存）
    python scripts/collect_all.py --no-cache # 强制重新抓取
    python scripts/collect_all.py --only github,bilibili

降级策略：某个平台抓取失败时，自动沿用上一次快照里该平台的数据，
并把它标记为 stale（页面会显示"数据更新于 X"），保证站点永不空白。
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import lib_model as M                      # noqa: E402
from lib_http import HttpClient, HttpError  # noqa: E402
import adapter_github                       # noqa: E402
import adapter_bilibili                     # noqa: E402
import adapter_netease                      # noqa: E402

CONFIG = os.path.join(ROOT, "config", "site.json")
SNAPSHOT = os.path.join(ROOT, "data", "snapshot.json")
CACHE = os.path.join(ROOT, ".cache", "http")

ADAPTERS = {
    "github": adapter_github,
    "bilibili": adapter_bilibili,
    "netease": adapter_netease,
}

ORDER = ["github", "bilibili", "netease"]


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--ttl", type=int, default=None)
    args = ap.parse_args()

    cfg = load_json(CONFIG)
    if not cfg:
        print("找不到配置：%s" % CONFIG)
        return 1

    ttl = 0 if args.no_cache else (args.ttl if args.ttl is not None
                                   else cfg["collect"]["cacheTtlSeconds"])
    client = HttpClient(cache_dir=CACHE, ttl=ttl,
                        delay=cfg["collect"]["requestDelaySeconds"])
    prev = load_json(SNAPSHOT, {}) or {}
    prev_platforms = {}
    for it in prev.get("items") or []:
        prev_platforms.setdefault(it["platform"], []).append(it)
    prev_collections = {}
    for c in prev.get("collections") or []:
        prev_collections.setdefault(c["platform"], []).append(c)
    prev_profiles = prev.get("profiles") or {}

    targets = [p.strip() for p in args.only.split(",") if p.strip()] or ORDER
    platforms = {}
    errors = []

    for name in targets:
        mod = ADAPTERS.get(name)
        if not mod:
            continue
        print("\n== 采集 %s ==" % name, flush=True)
        t0 = time.time()
        try:
            res = mod.collect(client, cfg, verbose=True)
        except HttpError as e:
            res = {"ok": False, "items": [], "collections": [], "profile": None,
                   "error": "网络错误：%s" % e}
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "items": [], "collections": [], "profile": None,
                   "error": "%s: %s" % (type(e).__name__, e)}

        ok = bool(res.get("ok"))
        if not ok:
            msg = "%s 采集失败（%s），沿用上次快照" % (name, res.get("error"))
            print("    ! " + msg, flush=True)
            errors.append(msg)
            res = {
                "ok": False,
                "items": prev_platforms.get(name, []),
                "collections": prev_collections.get(name, []),
                "profile": prev_profiles.get(name),
                "playerData": prev.get("player") or {},
                "stale": True,
                "error": res.get("error"),
            }
        res["fetchedAt"] = M.iso(time.time())
        res["seconds"] = round(time.time() - t0, 1)
        platforms[name] = res
        print("    完成，用时 %.1fs，%s" % (res["seconds"], client.report()), flush=True)

    # 未参与本次采集的平台，直接沿用旧数据。
    # 注意：不要把 prev 的整个 player 塞进来——那会覆盖已采集平台的新数据
    # （player.update 是后写覆盖先写）。没采集的平台本来就没有播放器数据。
    for name in ORDER:
        if name not in platforms:
            platforms[name] = {
                "ok": True, "items": prev_platforms.get(name, []),
                "collections": prev_collections.get(name, []),
                "profile": prev_profiles.get(name), "fetchedAt": None,
            }

    snapshot = M.build_snapshot(platforms, errors=errors)
    snapshot["fingerprint"] = M.content_fingerprint(snapshot)
    old_fp = prev.get("fingerprint")
    snapshot["changed"] = old_fp != snapshot["fingerprint"]

    save_json(SNAPSHOT, snapshot)

    print("\n" + "=" * 62)
    print("快照已写入 %s" % os.path.relpath(SNAPSHOT, ROOT))
    print("生成时间：%s" % snapshot["generatedAt"])
    print("内容指纹：%s%s" % (snapshot["fingerprint"],
                            "" if old_fp is None else ("（与上次相同）" if not snapshot["changed"] else "（有新内容）")))
    print("-" * 62)
    by_type = {}
    for it in snapshot["items"]:
        by_type[(it["platform"], it["type"])] = by_type.get((it["platform"], it["type"]), 0) + 1
    for (p, t), n in sorted(by_type.items()):
        print("  %-10s %-8s %4d" % (p, t, n))
    print("  %-10s %-8s %4d" % ("总计", "", len(snapshot["items"])))
    print("-" * 62)
    for name, st in snapshot["platformStatus"].items():
        flag = "正常" if st["ok"] else ("沿用旧数据" if st["itemCount"] else "无数据")
        print("  %-10s %-10s %4d 条  最新 %s" % (
            name, flag, st["itemCount"], (st["latestAt"] or "-")[:10]))
    if errors:
        print("-" * 62)
        for e in errors:
            print("  ! " + e)
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
