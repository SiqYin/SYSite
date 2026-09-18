"""统一内容模型。

三个平台的原始数据差异极大，这里把它们压成同一种结构。
页面渲染层只认这个结构 —— 新增平台时只需再写一个适配器，前端一行不用改。
"""

import hashlib
import time

# 内容类型
VIDEO = "video"
AUDIO = "audio"
PROJECT = "project"
POST = "post"          # 图文 / 动态 / 文章
COLLECTION = "collection"


def make_id(platform, native_id):
    return "%s:%s" % (platform, native_id)


def clean_text(s, limit=None):
    if not s:
        return ""
    s = " ".join(str(s).replace("\u3000", " ").split())
    if limit and len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s


def iso(ts):
    """秒级时间戳 -> ISO8601 字符串（本地无时区依赖，按 UTC 存）。"""
    if not ts:
        return None
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return None
    if ts > 1e11:  # 毫秒
        ts = ts / 1000.0
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def item(platform, native_id, type_, title, url, **kw):
    """构造一条统一内容。"""
    it = {
        "id": make_id(platform, native_id),
        "platform": platform,
        "nativeId": str(native_id),
        "type": type_,
        "title": clean_text(title, 200),
        "url": url,
        "cover": None,
        "coverRemote": None,
        "publishedAt": None,
        "description": "",
        "tags": [],
        "stats": {},
        "durationSec": None,
        "embed": None,
        "collections": [],
        "pinned": False,
        "extra": {},
    }
    it.update(kw)
    if it["publishedAt"] is None and "publishedTs" in kw:
        it["publishedAt"] = iso(kw["publishedTs"])
    return it


def collection(platform, native_id, title, url, **kw):
    it = {
        "id": make_id(platform, native_id),
        "platform": platform,
        "nativeId": str(native_id),
        "type": COLLECTION,
        "title": clean_text(title, 120),
        "url": url,
        "cover": None,
        "coverRemote": None,
        "publishedAt": None,
        "description": clean_text(kw.get("description"), 300),
        "itemCount": kw.get("itemCount") or 0,
        "memberIds": kw.get("memberIds") or [],
        "extra": kw.get("extra") or {},
    }
    return it


def dedupe(items):
    """同 id 只保留一条；后者覆盖前者但保留已有的非空字段。"""
    out = {}
    for it in items:
        key = it["id"]
        if key in out:
            merged = dict(out[key])
            for k, v in it.items():
                if v not in (None, "", [], {}, False) or k in ("pinned",):
                    merged[k] = v
            out[key] = merged
        else:
            out[key] = it
    return list(out.values())


def sort_key(it):
    return (it.get("publishedAt") or "", it.get("id") or "")


def build_snapshot(platforms, generated_at=None, errors=None):
    """把各平台结果合并成一份快照。"""
    all_items = []
    all_collections = []
    profiles = {}
    player = {}
    for name, payload in platforms.items():
        all_items.extend(payload.get("items") or [])
        all_collections.extend(payload.get("collections") or [])
        if payload.get("profile"):
            profiles[name] = payload["profile"]
        # 自建播放器所需的运行时数据（音频直链、歌词），按歌曲 id 汇总
        player.update(payload.get("playerData") or {})

    all_items = dedupe(all_items)
    latest = {}
    for it in all_items:
        p = it["platform"]
        if it.get("publishedAt") and (p not in latest or it["publishedAt"] > latest[p]):
            latest[p] = it["publishedAt"]

    return {
        "schemaVersion": 1,
        "generatedAt": generated_at or iso(time.time()),
        "profiles": profiles,
        "player": player,
        "items": sorted(all_items, key=sort_key, reverse=True),
        "collections": sorted(all_collections, key=lambda c: c.get("title") or ""),
        "platformStatus": {
            name: {
                "ok": payload.get("ok", False),
                "itemCount": len(payload.get("items") or []),
                "collectionCount": len(payload.get("collections") or []),
                "latestAt": latest.get(name),
                "error": payload.get("error"),
                "fetchedAt": payload.get("fetchedAt"),
            }
            for name, payload in platforms.items()
        },
        "errors": errors or [],
    }


def content_fingerprint(snapshot):
    """用于判断内容是否变化（决定要不要重建站点）。"""
    parts = []
    for it in snapshot.get("items") or []:
        parts.append("%s|%s|%s|%s" % (it["id"], it.get("title"), it.get("publishedAt"),
                                      (it.get("stats") or {}).get("view") or (it.get("stats") or {}).get("play")))
    raw = "\n".join(sorted(parts))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
