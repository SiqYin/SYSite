"""构建期资源管道：把第三方图床的封面下载、压缩、自托管。

为什么不在页面里直接热链平台图床：
1. 国内访问 hdslb / music.126.net 的稳定性不由我们控制，图挂了整页就花；
2. 平台可能加防盗链；
3. 原图很大（网易云单张 1.3MB），必须压缩。

产出：src/assets/covers/*.webp，并把快照里的 cover 字段改成本地路径。
缺 Pillow 时自动降级为保留远程直链，不阻塞构建。
"""

import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import ssl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

SNAPSHOT = os.path.join(ROOT, "data", "snapshot.json")
OUTDIR = os.path.join(ROOT, "src", "assets", "covers")
CACHE = os.path.join(ROOT, ".cache", "img")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def safe_name(s):
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s[:80]


def url_key(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def download(url, referer=None):
    p = os.path.join(CACHE, url_key(url) + ".raw")
    if os.path.exists(p) and os.path.getsize(p) > 512:
        with open(p, "rb") as f:
            return f.read()
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=30, context=_CTX) as r:
            body = r.read()
    except (urllib.error.URLError, OSError, ValueError) as e:
        print("    ! 下载失败 %s（%s）" % (url[:70], e))
        return None
    if len(body) < 512:
        return None
    os.makedirs(CACHE, exist_ok=True)
    with open(p, "wb") as f:
        f.write(body)
    return body


def convert(body, out_path, width, quality, crop_square=False):
    """转成 webp；缺 Pillow 时原样落盘为 jpg。"""
    if HAS_PIL:
        try:
            im = Image.open(io.BytesIO(body))
            im.load()
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            if crop_square:
                w, h = im.size
                side = min(w, h)
                im = im.crop(((w - side) // 2, (h - side) // 2,
                              (w - side) // 2 + side, (h - side) // 2 + side))
            if im.width > width:
                ratio = width / im.width
                im = im.resize((width, max(1, round(im.height * ratio))), Image.LANCZOS)
            if im.mode == "RGBA":
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[3])
                im = bg
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            im.save(out_path, "WEBP", quality=quality, method=5)
            return True
        except Exception as e:  # noqa: BLE001
            print("    ! 转换失败 %s：%s" % (os.path.basename(out_path), e))
    return False


def main():
    cfg = json.load(open(os.path.join(ROOT, "config", "site.json"), "r", encoding="utf-8"))
    snap = json.load(open(SNAPSHOT, "r", encoding="utf-8"))
    width = cfg["assets"]["coverWidth"]
    quality = cfg["assets"]["coverQuality"]
    limit = cfg["assets"]["maxCovers"]

    os.makedirs(OUTDIR, exist_ok=True)
    seen = {}          # 远程 url -> 本地相对路径
    done = failed = reused = 0
    t0 = time.time()

    if not HAS_PIL:
        print("  ! 未安装 Pillow，封面将保持远程直链（页面可用，但依赖平台图床）")

    def handle(url, item_id, referer, crop=False, folder="covers", w=None):
        nonlocal done, failed, reused
        if not url:
            return None
        if url in seen:
            reused += 1
            return seen[url]
        ext = "webp" if HAS_PIL else "jpg"
        name = "%s_%s.%s" % (safe_name(item_id), url_key(url)[:8], ext)
        rel = "assets/%s/%s" % (folder, name)
        out = os.path.join(ROOT, "src", rel)
        if os.path.exists(out) and os.path.getsize(out) > 512:
            seen[url] = rel
            reused += 1
            return rel
        if done + failed >= limit:
            return url
        body = download(url, referer)
        if not body:
            failed += 1
            return url
        if HAS_PIL and convert(body, out, w or width, quality, crop):
            seen[url] = rel
            done += 1
            return rel
        # 降级：原图落盘
        out2 = os.path.join(ROOT, "src", "assets", folder, name.rsplit(".", 1)[0] + ".jpg")
        os.makedirs(os.path.dirname(out2), exist_ok=True)
        with open(out2, "wb") as f:
            f.write(body)
        rel2 = "assets/%s/%s" % (folder, os.path.basename(out2))
        seen[url] = rel2
        done += 1
        return rel2

    print("== 处理头像 ==")
    for platform, prof in (snap.get("profiles") or {}).items():
        if prof.get("avatar"):
            prof["avatarLocal"] = handle(prof["avatar"], "%s_avatar" % platform,
                                         None, crop=True, folder="avatars",
                                         w=cfg["assets"]["avatarSize"])
    snap["profilesLocalReady"] = True

    print("== 处理封面 ==")
    for it in snap["items"]:
        src = it.get("coverRemote")
        if not src:
            continue
        ref = None
        if it["platform"] == "bilibili":
            ref = "https://www.bilibili.com/"
        elif it["platform"] == "netease":
            ref = "https://music.163.com/"
        local = handle(src, it["id"], ref)
        if local and local != src:
            it["cover"] = local

    print("== 处理文集封面 ==")
    for c in snap.get("collections") or []:
        src = (c.get("extra") or {}).get("coverRemote")
        if not src:
            continue
        local = handle(src, "col_" + c["id"], "https://www.bilibili.com/")
        if local and local != src:
            c["cover"] = local

    print("== 处理创作者头像（各平台）==")
    print("  下载/转换 %d 张，复用 %d 张，失败 %d 张，用时 %.1fs"
          % (done, reused, failed, time.time() - t0))

    total = 0
    for dp, dn, fn in os.walk(os.path.join(ROOT, "src", "assets")):
        for f in fn:
            total += os.path.getsize(os.path.join(dp, f))
    print("  本地图片总大小：%.1f MB" % (total / 1048576))

    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    print("  快照已更新本地图片路径")
    return 0


if __name__ == "__main__":
    sys.exit(main())
