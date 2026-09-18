"""哔哩哔哩适配器。

关键结论（已实测）：
- Web 端投稿接口 /x/space/wbi/arc/search 受风控（-352），不可用。
- App 端 /x/v2/space/archive/cursor 可用，必须用 appkey/appsec 做 MD5 签名，
  并以 aid 作游标翻页（首页带 include_cursor=true），实测可拿全量视频。
- 图文用 opus/feed/space 的 offset 游标翻页；音频用 music-service 接口。
- 置顶视频 /x/space/top/arc 直接可用。
- 文集（合集）用 seasons_series_list + seasons_archives_list。
"""

import hashlib
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_model as M  # noqa: E402

APPKEY = "dfca71928277209b"
APPSEC = "b5475a8825547a4fc26c7d518eaaa02e"
APP_UA = ("Mozilla/5.0 BiliDroid/8.43.0 (bbcallen@gmail.com) os/android model/android "
          "mobi_app/android build/8430300 channel/master innerVer/8430300 osVer/15 network/2")
APP_STAT = '{"appId":1,"platform":3,"version":"8.43.0","abtest":""}'
APP_BUILD = 8430300
APP_VERSION = "8.43.0"
APP_BASE = "https://app.bilibili.com"
WEB_REF = "https://space.bilibili.com/%s"


def _enc(v):
    return urllib.parse.quote(str(v), safe="").replace("+", "%20")


def app_sign(params):
    """PiliPlus 同款签名：参数字典序拼接 + appsec 做 MD5。"""
    p = {k: v for k, v in params.items() if v is not None}
    p["appkey"] = APPKEY
    p["ts"] = str(int(time.time()))
    q = "&".join("%s=%s" % (_enc(k), _enc(v)) for k, v in sorted(p.items()))
    p["sign"] = hashlib.md5((q + APPSEC).encode()).hexdigest()
    return "&".join("%s=%s" % (_enc(k), _enc(v)) for k, v in sorted(p.items()))


def _https(url):
    """B 站图片字段有时是字符串、有时是对象或列表，统一兜底。"""
    if not url:
        return None
    if isinstance(url, (list, tuple)):
        url = url[0] if url else None
    if isinstance(url, dict):
        url = url.get("url") or url.get("src") or url.get("cover")
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    return url.replace("http://", "https://", 1)


def _ts(v, default=None):
    """B 站时间字段可能是秒级时间戳或 '2026-09-10' 这样的文本。"""
    if v in (None, ""):
        return default
    if isinstance(v, (int, float)):
        return M.iso(v)
    s = str(v)
    if s.isdigit():
        return M.iso(int(s))
    return s if len(s) >= 10 else default


class BilibiliAdapter:
    def __init__(self, client, cfg, verbose=True):
        self.c = client
        self.cfg = cfg
        self.verbose = verbose
        self.mid = cfg["accounts"]["bilibili"]["mid"]
        self.ref = WEB_REF % self.mid
        self.limit_detail = cfg["collect"]["bilibiliDetailLimit"]

    def log(self, msg):
        if self.verbose:
            print(msg, flush=True)

    # ---------- 用户信息 ----------
    def profile(self):
        d = self.c.get_json("https://api.bilibili.com/x/web-interface/card?mid=%s&photo=false" % self.mid,
                            referer=self.ref)
        if d.get("code") != 0:
            return None
        c = d["data"]["card"]
        return {
            "platform": "bilibili",
            "name": c.get("name"),
            "handle": "UID %s" % self.mid,
            "avatar": _https(c.get("face")),
            "url": "https://space.bilibili.com/%s" % self.mid,
            "bio": M.clean_text(c.get("sign"), 200),
            "stats": {
                "followers": d["data"].get("follower"),
                "following": d["data"].get("following"),
                "likes": d["data"].get("like_num"),
            },
            "level": (c.get("level_info") or {}).get("current_level"),
        }

    # ---------- 视频全量 ----------
    def videos(self, max_pages=12):
        out, seen = [], set()
        cursor = None
        for step in range(1, max_pages + 1):
            params = {
                "build": APP_BUILD, "version": APP_VERSION, "c_locale": "zh_CN",
                "channel": "master", "mobi_app": "android", "platform": "android",
                "s_locale": "zh_CN", "ps": 20, "qn": 80, "order": "pubdate",
                "statistics": APP_STAT, "vmid": self.mid,
            }
            if cursor is None:
                params["pn"] = 1
                params["include_cursor"] = "true"
            else:
                params["aid"] = cursor
            url = APP_BASE + "/x/v2/space/archive/cursor?" + app_sign(params)
            d = self.c.get_json(url, headers={"User-Agent": APP_UA, "env": "prod",
                                              "app-key": "android64",
                                              "x-bili-aurora-zone": "sh001"})
            if d.get("code") != 0:
                self.log("    ! 视频第 %d 页失败：%s" % (step, d.get("message")))
                break
            data = d.get("data") or {}
            items = data.get("item") or []
            fresh = [v for v in items if v.get("bvid") and v["bvid"] not in seen]
            for v in fresh:
                seen.add(v["bvid"])
            out.extend(fresh)
            self.log("    视频第 %d 页：%d 条（新增 %d，累计 %d，接口计数 %s）"
                     % (step, len(items), len(fresh), len(out), data.get("count")))
            if not fresh or not data.get("has_next"):
                break
            cursor = fresh[-1].get("param")
            if not cursor:
                break
            time.sleep(self.c.delay or 0.7)
        return out

    # ---------- 专栏文集（图文只取文集里的文章）----------
    def article_lists(self):
        """返回该 UP 主的专栏文集列表。"""
        d = self.c.get_json("https://api.bilibili.com/x/article/up/lists?mid=%s&sort=0" % self.mid,
                            referer=self.ref + "/article")
        if d.get("code") != 0:
            self.log("    ! 专栏文集列表失败：%s" % d.get("message"))
            return []
        lists = (d.get("data") or {}).get("lists") or []
        self.log("    专栏文集：%d 个" % len(lists))
        return lists

    def list_articles(self, list_id, count=0):
        """取某个文集内的全部文章，按 articles_count 推算页数并去重。"""
        out, seen = [], set()
        pages = max(2, int(count or 0) // 30 + 2)
        for pn in range(1, pages + 1):
            d = self.c.get_json(
                "https://api.bilibili.com/x/article/list/web/articles?id=%s&page=%d" % (list_id, pn),
                referer=self.ref + "/article")
            if d.get("code") != 0:
                self.log("    ! 文集 %s 第 %d 页失败：%s" % (list_id, pn, d.get("message")))
                break
            arts = (d.get("data") or {}).get("articles") or []
            fresh = [a for a in arts if a.get("id") and a["id"] not in seen]
            for a in fresh:
                seen.add(a["id"])
            out.extend(fresh)
            if len(arts) < 30 or not fresh:
                break
            time.sleep(self.c.delay or 0.7)
        return out

    # ---------- 置顶视频 ----------
    def top_arc(self):
        d = self.c.get_json("https://api.bilibili.com/x/space/top/arc?vmid=%s" % self.mid,
                            referer=self.ref)
        if d.get("code") != 0 or not d.get("data"):
            return None
        return d["data"]

    # ---------- 文集 / 合集 ----------
    def seasons(self):
        d = self.c.get_json(
            "https://api.bilibili.com/x/polymer/web-space/seasons_series_list"
            "?mid=%s&page_num=1&page_size=20" % self.mid, referer=self.ref)
        if d.get("code") != 0:
            return []
        lists = (d.get("data") or {}).get("items_lists") or {}
        return lists.get("seasons_list") or []

    def season_archives(self, season_id, total):
        out = []
        for pn in range(1, max(2, total // 30 + 2)):
            d = self.c.get_json(
                "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list"
                "?mid=%s&season_id=%s&sort_reverse=false&page_num=%d&page_size=30"
                % (self.mid, season_id, pn), referer=self.ref)
            if d.get("code") != 0:
                break
            arch = (d.get("data") or {}).get("archives") or []
            out.extend(arch)
            if len(arch) < 30:
                break
            time.sleep(self.c.delay or 0.7)
        return out


def collect(client, cfg, verbose=True):
    ad = BilibiliAdapter(client, cfg, verbose)
    result = {"ok": False, "items": [], "collections": [], "profile": None}

    result["profile"] = ad.profile()
    videos = ad.videos()
    top = ad.top_arc()
    seasons = ad.seasons()
    art_lists = ad.article_lists()

    # 视频合集 → 作为视频的分组标签
    member_of = {}
    for s in seasons:
        meta = s.get("meta") or {}
        sid = meta.get("season_id")
        title = meta.get("title")
        arch = ad.season_archives(sid, meta.get("total") or 0)
        ids = []
        for a in arch:
            bv = a.get("bvid")
            if not bv:
                continue
            member_of.setdefault(bv, []).append(title)
            ids.append(M.make_id("bilibili", bv))
        result["collections"].append(M.collection(
            "bilibili", "season%s" % sid, title,
            "https://space.bilibili.com/%s/channel/collectiondetail?sid=%s" % (ad.mid, sid),
            description=meta.get("description"),
            itemCount=len(ids), memberIds=ids,
            extra={"kind": "season", "coverRemote": _https(meta.get("cover"))},
        ))

    top_bvid = (top or {}).get("bvid")

    for v in videos:
        bvid = v["bvid"]
        result["items"].append(M.item(
            "bilibili", bvid, M.VIDEO,
            v.get("title"),
            "https://www.bilibili.com/video/%s" % bvid,
            coverRemote=_https(v.get("cover")),
            publishedAt=_ts(v.get("ctime")),
            publishedTs=v.get("ctime"),
            description="",
            tags=[t for t in [v.get("tname")] if t],
            stats={"play": v.get("play"), "danmaku": v.get("danmaku")},
            durationSec=v.get("duration"),
            embed={"kind": "bilibili", "bvid": bvid, "cid": v.get("first_cid"), "aspect": "16:9"},
            collections=member_of.get(bvid, []),
            pinned=(bvid == top_bvid),
            extra={"author": v.get("author"), "videos": v.get("videos"), "aid": v.get("param")},
        ))

    # 置顶视频若不在投稿列表里，补一条（通常已包含，这里兜底）
    if top and top_bvid and not any(i["id"] == M.make_id("bilibili", top_bvid) for i in result["items"]):
        result["items"].append(M.item(
            "bilibili", top_bvid, M.VIDEO, top.get("title"),
            "https://www.bilibili.com/video/%s" % top_bvid,
            coverRemote=_https(top.get("pic")), publishedTs=top.get("pubdate"),
            description=M.clean_text(top.get("desc"), 300),
            tags=[t for t in [top.get("tname")] if t],
            stats={"play": (top.get("stat") or {}).get("view"),
                   "danmaku": (top.get("stat") or {}).get("danmaku")},
            durationSec=top.get("duration"),
            embed={"kind": "bilibili", "bvid": top_bvid, "aspect": "16:9"},
            pinned=True,
            extra={"author": (top.get("owner") or {}).get("name")},
        ))

    # 专栏文集 → 图文只取文集内的文章
    article_total = 0
    for L in art_lists:
        lid = L.get("id")
        name = L.get("name")
        count = L.get("articles_count") or 0
        arts = ad.list_articles(lid, count)
        article_total += len(arts)
        ids = []
        for a in arts:
            aid = a.get("id")
            ids.append(M.make_id("bilibili", "cv%s" % aid))
            imgs = a.get("image_urls") or []
            cats = [c.get("name") for c in (a.get("categories") or []) if c.get("name")]
            st = a.get("stats") or {}
            result["items"].append(M.item(
                "bilibili", "cv%s" % aid, M.POST,
                a.get("title"),
                "https://www.bilibili.com/read/cv%s" % aid,
                coverRemote=_https(imgs[0] if imgs else None),
                publishedTs=a.get("publish_time"),
                description=M.clean_text(a.get("summary"), 300),
                tags=cats,
                stats={"view": st.get("view"), "like": st.get("like"),
                       "reply": st.get("reply"), "favorite": st.get("favorite")},
                collections=[name],
                extra={"words": a.get("words"), "dynId": a.get("dyn_id_str"),
                       "listId": str(lid)},
            ))
        result["collections"].append(M.collection(
            "bilibili", "cvlist%s" % lid, name,
            "https://www.bilibili.com/read/readlist/rl%s" % lid,
            description=L.get("summary"),
            itemCount=len(ids), memberIds=ids,
            extra={"kind": "article-list", "coverRemote": _https(L.get("image_url")),
                   "words": L.get("words"), "read": L.get("read"),
                   "publishedTs": L.get("publish_time"), "articlesCount": count},
        ))
        time.sleep(0.5)

    if videos:
        result["ok"] = True
    else:
        result["error"] = "视频列表为空"

    if verbose:
        print("    B站汇总：视频 %d / 文集 %d 个·文章 %d / 视频合集 %d"
              % (len(videos), len(art_lists), article_total, len(seasons)))
    return result
