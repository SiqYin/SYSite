"""网易云音乐适配器。

实测可用的公开接口（无需登录、无需加密签名）：
- /api/artist/{id}              歌手信息 + hotSongs
- /api/artist/albums/{id}       全部专辑
- /api/artist/top/song          全部歌曲（含所属专辑），返回顺序即官方热度序
- /api/song/detail?ids=[...]    批量取歌曲详情，album.publishTime 即发布时间
- /api/v1/resource/comments/R_SO_4_{id}   评论数（做热度排序用）

为什么热度用评论数而不是 popularity：
popularity 只有 5 档（25/20/15/10/5），43 首里 29 首并列为 10，排不出名次；
评论数是真实且分散的公开指标。两者都会存进快照。

播放走官方 outchain 播放器 iframe（无 X-Frame-Options，可嵌入）。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_model as M  # noqa: E402

REF = "https://music.163.com/"
EMBED_SONG = "https://music.163.com/outchain/player?type=2&id=%s&auto=0&height=66"


def _pic(url, size=400):
    if not url:
        return None
    base = url.split("?")[0]
    return "%s?param=%dy%d" % (base, size, size)


def fetch_song_details(client, ids, chunk=10):
    """批量取歌曲详情，主要为了 album.publishTime（发布时间）。
    注意：一次塞太多 id 时接口会返回精简结构、publishTime 被置 0，所以分块。"""
    out = {}
    for i in range(0, len(ids), chunk):
        part = ids[i:i + chunk]
        try:
            d = client.get_json(
                "https://music.163.com/api/song/detail?ids=[%s]" % ",".join(str(x) for x in part),
                referer=REF)
        except Exception:  # noqa: BLE001
            continue
        for s in d.get("songs") or []:
            al = s.get("album") or {}
            out[str(s.get("id"))] = {
                "publishTs": (al.get("publishTime") or 0) / 1000 or None,
                "albumName": al.get("name"),
                "albumId": al.get("id"),
                "albumPic": al.get("picUrl"),
            }
    return out


def fetch_comment_counts(client, ids, delay=0.6):
    """逐首取评论数。失败即跳过，不阻塞整体采集。"""
    out = {}
    for i, sid in enumerate(ids):
        try:
            d = client.get_json(
                "https://music.163.com/api/v1/resource/comments/R_SO_4_%s?limit=1&offset=0" % sid,
                referer=REF)
            if isinstance(d.get("total"), int):
                out[str(sid)] = d["total"]
        except Exception:  # noqa: BLE001
            pass
        if delay and i < len(ids) - 1:
            time.sleep(delay)
    return out


def collect(client, cfg, verbose=True):
    artist_id = cfg["accounts"]["netease"]["artistId"]
    limit = cfg["collect"]["neteaseSongLimit"]
    result = {"ok": False, "items": [], "collections": [], "profile": None}

    try:
        art = client.get_json("https://music.163.com/api/artist/%s" % artist_id, referer=REF)
    except Exception as e:  # noqa: BLE001
        result["error"] = "歌手信息获取失败：%s" % e
        return result

    a = art.get("artist") or {}
    result["profile"] = {
        "platform": "netease",
        "name": a.get("name"),
        "handle": "网易音乐人 %s" % artist_id,
        "avatar": _pic(a.get("picUrl"), 300),
        "url": "https://music.163.com/#/artist?id=%s" % artist_id,
        "bio": M.clean_text(a.get("briefDesc"), 300),
        "stats": {
            "albums": a.get("albumSize"),
            "songs": a.get("musicSize"),
        },
    }

    albums = []
    try:
        alb = client.get_json("https://music.163.com/api/artist/albums/%s?limit=60" % artist_id,
                              referer=REF)
        albums = alb.get("hotAlbums") or []
    except Exception as e:  # noqa: BLE001
        if verbose:
            print("    ! 专辑列表获取失败：%s" % e)

    songs = []
    try:
        top = client.get_json("https://music.163.com/api/artist/top/song?id=%s" % artist_id,
                              referer=REF)
        songs = top.get("songs") or []
    except Exception as e:  # noqa: BLE001
        if verbose:
            print("    ! 歌曲列表获取失败：%s" % e)
    if not songs:
        songs = art.get("hotSongs") or []

    if verbose:
        print("    专辑 %d 张，歌曲 %d 首" % (len(albums), len(songs)))

    album_by_id = {}
    for al in albums:
        aid = al.get("id")
        album_by_id[aid] = al
        result["items"].append(M.item(
            "netease", "album%s" % aid, M.AUDIO,
            al.get("name"),
            "https://music.163.com/#/album?id=%s" % aid,
            coverRemote=_pic(al.get("picUrl") or al.get("blurPicUrl"), 500),
            publishedTs=(al.get("publishTime") or 0) / 1000 or None,
            description=M.clean_text(al.get("description") or al.get("company"), 200),
            tags=[al.get("type") or "", al.get("subType") or ""],
            extra={"isAlbum": True, "songCount": al.get("size"), "company": al.get("company")},
        ))

    seen_songs = set()
    picked = []
    for s in songs[:limit]:
        if s.get("id") in seen_songs:
            continue
        seen_songs.add(s.get("id"))
        picked.append(s)

    # 发布时间：批量取 song/detail 里的 album.publishTime
    details = fetch_song_details(client, [s["id"] for s in picked])
    # 热度：评论数
    comments = fetch_comment_counts(client, [s["id"] for s in picked],
                                    delay=cfg["collect"].get("commentDelaySeconds", 0.6))
    if verbose:
        print("    歌曲详情 %d 首 / 评论数 %d 首" % (len(details), len(comments)))

    for s in picked:
        sid = s.get("id")
        det = details.get(str(sid)) or {}
        al = (s.get("al") or s.get("album") or {})
        album_id = al.get("id") or det.get("albumId")
        cover = _pic(al.get("picUrl") or det.get("albumPic")
                     or (album_by_id.get(album_id) or {}).get("picUrl"), 500)
        pub_ts = det.get("publishTs")
        if not pub_ts:
            a0 = album_by_id.get(album_id) or {}
            pub_ts = (a0.get("publishTime") or 0) / 1000 or None
        cmt = comments.get(str(sid))
        result["items"].append(M.item(
            "netease", "song%s" % sid, M.AUDIO,
            s.get("name"),
            "https://music.163.com/#/song?id=%s" % sid,
            coverRemote=cover,
            publishedTs=pub_ts,
            description=M.clean_text((s.get("alias") or [""])[0], 120),
            tags=[al.get("name") or ""],
            stats={
                "comments": cmt,
                "popularity": s.get("pop"),
                "duration": s.get("dt") or s.get("duration"),
            },
            durationSec=round((s.get("dt") or s.get("duration") or 0) / 1000) or None,
            embed={"kind": "netease", "songId": sid, "src": EMBED_SONG % sid},
            extra={"album": al.get("name") or det.get("albumName"),
                   "albumId": album_id,
                   "artist": ", ".join(x.get("name", "") for x in (s.get("ar") or s.get("artists") or []))},
        ))

    result["ok"] = bool(songs or albums)
    if not result["ok"]:
        result["error"] = "歌曲与专辑均为空"
    return result
