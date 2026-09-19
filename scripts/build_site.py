"""静态站点渲染层。

只读取 data/snapshot.json（统一内容模型）与 src/ 下的模板资源，
不直接接触任何平台接口 —— 这样新增平台时前端一行都不用改。

页面（每种语言各一套，共 4 套）：
    index.html     首页（精选 + 各区块预览）
    videos.html    全部视频（带排序）
    music.html     全部音乐（带排序）
    articles.html  文集与全部文章
    projects.html  开源项目（按更新时间倒序）
    about.html     关于
    search.html    站内搜索（构建期生成索引，运行时本地过滤）

排序默认：热度倒序。视频热度取播放量，音乐热度取评论数（理由见 adapter_netease.py）。

用法：
    python scripts/build_site.py [--serve] [--clean]
"""

import argparse
import calendar
import html
import hashlib
import json
import os
import time
import re
import shutil
import sys
import time
from urllib.parse import quote

try:
    import segno
except ImportError:
    segno = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")
SRC = os.path.join(ROOT, "src")

SNAPSHOT = os.path.join(ROOT, "data", "snapshot.json")
CURATED = os.path.join(ROOT, "data", "curated.json")
CONFIG = os.path.join(ROOT, "config", "site.json")

LOCALES = [
    ("zh-CN", "简体中文", ""),
    ("zh-TW", "繁體中文", "zh-TW"),
    ("en", "English", "en"),
    ("ja", "日本語", "ja"),
]

PLATFORM_LABEL = {"bilibili": "哔哩哔哩", "netease": "网易云音乐", "github": "GitHub"}
PLATFORM_SHORT = {"bilibili": "B站", "netease": "网易云", "github": "GitHub"}

NAV = [
    ("index", "nav.home"),
    ("videos", "nav.videos"),
    ("music", "nav.music"),
    ("articles", "nav.articles"),
    ("projects", "nav.projects"),
    ("stats", "nav.stats"),
    ("about", "nav.about"),
]
PAGES = [p for p, _ in NAV] + ["search"]


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def clean_dir(path):
    """整目录清空（仅 --clean 时使用）。

    本机沙箱会把逐个 unlink 改写成回收站操作，删 300+ 文件要上百秒，
    所以默认构建不清空 dist，只原地覆盖。
    """
    if not os.path.isdir(path):
        return
    for dp, dns, fns in os.walk(path, topdown=False):
        for f in fns:
            try:
                os.unlink(os.path.join(dp, f))
            except OSError:
                pass
        for d in dns:
            try:
                os.rmdir(os.path.join(dp, d))
            except OSError:
                pass


def to_epoch(iso):
    if not iso:
        return 0
    s = str(iso)
    for fmt, ln in (("%Y-%m-%dT%H:%M:%SZ", 20), ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return calendar.timegm(time.strptime(s[:ln], fmt))
        except (ValueError, TypeError):
            continue
    digits = re.sub(r"\D", "", s)[:14]
    if len(digits) >= 8:
        try:
            return calendar.timegm(time.strptime(digits[:14].ljust(14, "0"), "%Y%m%d%H%M%S"))
        except ValueError:
            pass
    return 0


def fmt_date(iso):
    return str(iso)[:10].replace("/", "-") if iso else ""


def fmt_duration(sec):
    try:
        sec = int(sec or 0)
    except (TypeError, ValueError):
        return ""
    if sec <= 0:
        return ""
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


def fmt_num(n):
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return ""
    if n >= 100000000:
        return "%.1f亿" % (n / 100000000.0)
    if n >= 10000:
        return "%.1f万" % (n / 10000.0)
    return format(n, ",") if n >= 1000 else str(n)


def bili_embed(bvid, cid=None):
    """B 站官方播放器嵌入地址。

    hideCoverInfo=1 会隐藏封面信息浮层（标题/UP 主那一条），
    这样我们自己在外层加标题栏就不会和它打架。
    注意：官方播放器**不支持 postMessage、也没有隐藏品牌 logo 的参数**，
    中间那套播放控件没法替换，只能在外层做遮罩（见 player.videoMasks 配置）。
    """
    q = ("bvid=%s&page=1&high_quality=1&danmaku=0&autoplay=0&muted=0"
         "&hideCoverInfo=1&as_wide=1" % quote(str(bvid)))
    if cid:
        q += "&cid=%s" % quote(str(cid))
    return "https://player.bilibili.com/player.html?" + q


class Builder:
    def __init__(self, locale, shared):
        self.locale = locale
        self.cfg = shared["cfg"]
        self.snap = shared["snap"]
        self.curated = shared["curated"]
        self.all_i18n = shared["i18n"]
        self.zh = self.all_i18n["zh-CN"]
        self.strings = dict(self.zh)
        self.strings.update({k: v for k, v in (self.all_i18n.get(locale) or {}).items()
                             if not k.startswith("_")})
        self.sub = dict((c, s) for c, _, s in LOCALES)[locale]
        self.prefix = "" if locale == "zh-CN" else "../"
        self.items = self.snap.get("items") or []
        self.collections = self.snap.get("collections") or []
        self.profiles = self.snap.get("profiles") or {}
        self.hidden = set(self.curated.get("hidden") or [])
        self._d = None

    def t(self, key):
        return self.strings.get(key) or self.zh.get(key) or key

    # ---------- 数据 ----------
    def data(self):
        if self._d is not None:
            return self._d
        items = [i for i in self.items if i["id"] not in self.hidden]
        videos = [i for i in items if i["type"] == "video"]
        songs = [i for i in items if i["type"] == "audio" and not (i.get("extra") or {}).get("isAlbum")]
        posts = [i for i in items if i["type"] == "post"]
        projects = [i for i in items if i["type"] == "project"]

        heat = lambda i: ((i.get("stats") or {}).get("comments") if i["type"] == "audio"  # noqa: E731
                          else (i.get("stats") or {}).get("play")) or 0
        videos.sort(key=lambda i: (heat(i), to_epoch(i.get("publishedAt"))), reverse=True)
        songs.sort(key=lambda i: (heat(i), to_epoch(i.get("publishedAt"))), reverse=True)
        projects.sort(key=lambda i: (i.get("publishedAt") or ""), reverse=True)
        posts.sort(key=lambda i: (i.get("publishedAt") or ""), reverse=True)

        featured_projects = [p for p in projects if p.get("pinned")]
        for fid in self.curated.get("featured") or []:
            for it in projects:
                if it["id"] == fid and it not in featured_projects:
                    featured_projects.append(it)

        article_lists = [c for c in self.collections if (c.get("extra") or {}).get("kind") == "article-list"]
        self._d = {
            "videos": videos, "songs": songs, "posts": posts, "projects": projects,
            "articleLists": article_lists, "featuredProjects": featured_projects,
            "topVideos": videos[:3], "topSongs": songs[:3], "heat": heat,
        }
        return self._d

    # ---------- 片段 ----------
    def media_card(self, it, square=False, delay=0, badge=None, sub=None, reveal=True):
        st = it.get("stats") or {}
        kind = "audio" if it["type"] == "audio" else "video"
        heat = st.get("comments") if kind == "audio" else st.get("play")
        bits = []
        if heat:
            bits.append("%s %s" % (fmt_num(heat),
                                   self.t("meta.comments") if kind == "audio" else self.t("meta.play")))
        d = fmt_date(it.get("publishedAt"))
        if d:
            bits.append(d)
        meta = " · ".join(bits)
        dur = fmt_duration(it.get("durationSec"))
        cover = it.get("cover")
        year = fmt_date(it.get("publishedAt"))[:4]
        cls = "card rise" if reveal else "card"
        img = ('<img src="%s%s" alt="%s" loading="lazy" decoding="async">'
               % (self.prefix, esc(cover), esc(it["title"])) if cover else "")
        badge_html = '<span class="badge">%s</span>' % esc(badge) if badge else ""
        dur_html = '<span class="dur">%s</span>' % esc(dur) if (dur and not square) else ""
        sub_html = '<div class="card-sub">%s</div>' % esc(sub) if sub else ""
        if kind == "audio":
            embed = (it.get("embed") or {}).get("src", "")
            song_id = str((it.get("embed") or {}).get("songId") or "")
            f_attrs = ' data-f-year="%s" data-f-album="%s" data-song="%s"' % (
                esc(year), esc(sub or ""), esc(song_id))
        else:
            embed = bili_embed((it.get("embed") or {}).get("bvid") or it["nativeId"],
                               (it.get("embed") or {}).get("cid"))
            f_attrs = ' data-f-year="%s" data-f-coll="%s"' % (esc(year), esc("|".join(it.get("collections") or [])))
        qr = "assets/qr/" + self.qr_name(it)
        return (
            '<article class="%s" data-delay="%d" data-play="1" data-kind="%s" tabindex="0" role="button" '
            'data-ts="%d" data-heat="%d" data-qr="%s"%s '
            'data-title="%s" data-meta="%s" data-embed="%s" data-source="%s" '
            'data-source-label="%s" data-platform="%s">'
            '<div class="card-cover%s">%s%s%s'
            '<span class="play-hint"><span class="ring">'
            '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></span></span></div>'
            '<div class="card-body"><h3 class="card-title">%s</h3>%s'
            '<div class="card-meta"><span>%s</span></div></div></article>'
        ) % (cls, delay, kind, to_epoch(it.get("publishedAt")), int(heat or 0), esc(qr), f_attrs,
             esc(it["title"]), esc(meta), esc(embed), esc(it["url"]),
             esc(self.t("player.openSourceAudio" if kind == "audio" else "player.openSource")),
             PLATFORM_LABEL.get(it["platform"], ""),
             " square" if square else "", img, badge_html, dur_html,
             esc(it["title"]), sub_html, esc(meta))

    def qr_name(self, it):
        """二维码文件名，与构建期生成的 PNG 保持一致。"""
        import re as _re
        return "%s-%s.png" % (it["platform"], _re.sub(r"[^A-Za-z0-9_.-]", "_", str(it["nativeId"]))[:60])

    def mini(self, it, rank):
        kind = "audio" if it["type"] == "audio" else "video"
        st = it.get("stats") or {}
        heat = st.get("comments") if kind == "audio" else st.get("play")
        bits = []
        if heat:
            bits.append("%s %s" % (fmt_num(heat),
                                   self.t("meta.comments") if kind == "audio" else self.t("meta.play")))
        d = fmt_date(it.get("publishedAt"))
        if d:
            bits.append(d)
        cover = it.get("cover")
        thumb = ('<span class="mini-thumb%s">%s</span>'
                 % (" sq" if kind == "audio" else "",
                    '<img src="%s%s" alt="" loading="lazy" decoding="async">' % (self.prefix, esc(cover))
                    if cover else ""))
        cls = "" if rank == 1 else (" r2" if rank == 2 else " r3")
        song_attr = ''
        if kind == "audio":
            sid = str((it.get("embed") or {}).get("songId") or "")
            song_attr = ' data-song="%s"' % esc(sid)
        embed = ((it.get("embed") or {}).get("src", "") if kind == "audio"
                 else bili_embed((it.get("embed") or {}).get("bvid") or it["nativeId"],
                                 (it.get("embed") or {}).get("cid")))
        qr = "assets/qr/" + self.qr_name(it)
        return (
            '<button class="mini" type="button" data-play="1" data-kind="%s" data-qr="%s"%s '
            'data-title="%s" data-meta="%s" data-embed="%s" data-source="%s" '
            'data-source-label="%s" data-platform="%s">%s'
            '<span class="mini-body"><span class="mini-title"><span class="mini-rank%s">%d</span>%s</span>'
            '<span class="mini-meta">%s</span></span></button>'
          ) % (kind, esc(qr), song_attr, esc(it["title"]), esc(" · ".join(bits)), esc(embed), esc(it["url"]),
               esc(self.t("player.openSourceAudio" if kind == "audio" else "player.openSource")),
               PLATFORM_LABEL.get(it["platform"], ""), thumb, cls, rank, esc(it["title"]),
               esc(" · ".join(bits)))

    def project_card(self, it, badge=None, delay=0):
        lang = (it.get("tags") or [None])[0]
        stars = (it.get("stats") or {}).get("stars") or 0
        bits = []
        if lang:
            bits.append('<span class="lang-dot"></span>%s' % esc(lang))
        if stars:
            bits.append("★ %s" % fmt_num(stars))
        d = fmt_date(it.get("publishedAt"))
        if d:
            bits.append(d)
        badge_html = '<span class="chip pin">%s</span>' % esc(badge) if badge else ""
        return ('<a class="card repo-card rise" data-delay="%d" href="%s" target="_blank" '
                'rel="noopener noreferrer"><div class="rname">%s</div>'
                '<div class="rdesc">%s</div><div class="rmeta">%s</div>%s</a>'
                ) % (delay, esc(it["url"]), esc(it["title"]), esc(it.get("description") or ""),
                     "".join("<span>%s</span>" % b for b in bits), badge_html)

    def post_row(self, it, delay=0):
        st = it.get("stats") or {}
        ex = it.get("extra") or {}
        bits = []
        if st.get("view"):
            bits.append("%s %s" % (fmt_num(st["view"]), self.t("meta.view")))
        if st.get("like"):
            bits.append("%s %s" % (fmt_num(st["like"]), self.t("meta.like")))
        if ex.get("words"):
            bits.append("%s %s" % (ex["words"], self.t("meta.words")))
        d = fmt_date(it.get("publishedAt"))
        if d:
            bits.append(d)
        cols = it.get("collections") or []
        chip = '<span class="chip">%s</span>' % esc(cols[0]) if cols else ""
        return ('<a class="post rise" data-delay="%d" href="%s" target="_blank" rel="noopener noreferrer">'
                '<p class="ptxt">%s</p><div class="pmeta">%s%s</div></a>'
                ) % (delay, esc(it["url"]), esc(it["title"]), chip,
                     "".join("<span>%s</span>" % esc(b) for b in bits))

    def collection_card(self, c, delay=0):
        ex = c.get("extra") or {}
        cover = c.get("cover")
        img = ('<img src="%s%s" alt="%s" loading="lazy" decoding="async">'
               % (self.prefix, esc(cover), esc(c["title"])) if cover else "")
        bits = ["%s %s" % (c.get("itemCount"), self.t("meta.pieces"))]
        if ex.get("words"):
            bits.append("%s %s" % (ex["words"], self.t("meta.words")))
        if ex.get("read"):
            bits.append("%s %s" % (fmt_num(ex["read"]), self.t("meta.view")))
        return ('<a class="card rise" data-delay="%d" href="%s" target="_blank" rel="noopener noreferrer">'
                '<div class="card-cover square">%s<span class="badge">%s</span></div>'
                '<div class="card-body"><h3 class="card-title">%s</h3>'
                '<div class="card-meta"><span>%s</span></div></div></a>'
                ) % (delay, esc(c["url"]), img, esc(self.t("card.collection")), esc(c["title"]),
                     esc(" · ".join(bits)))

    def sortbar(self, target):
        """排序控件。默认热度倒序（最火在上），与页面初始渲染顺序一致。
        热度放在左边，因为它是默认排序依据。"""
        return ('<div class="sortbar" data-sortbar="%s" data-mode="heat" data-dir="desc">'
                '<div class="seg">'
                '<button class="seg-btn" data-set-mode="heat">%s</button>'
                '<button class="seg-btn" data-set-mode="time">%s</button></div>'
                '<button class="dir-btn" data-toggle-dir data-dir="desc">'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M19 12l-7 7-7-7"/></svg>'
                '<span data-dir-label>%s</span></button></div>'
                ) % (target, esc(self.t("sort.heat")), esc(self.t("sort.time")), esc(self.t("sort.desc")))

    def view_switch(self):
        """网格 / 时间轴切换。时间轴的年份分隔条由前端按当前顺序插入。"""
        return ('<div class="seg view-switch" data-view-switch>'
                '<button class="seg-btn on" data-set-view="grid">%s</button>'
                '<button class="seg-btn" data-set-view="timeline">%s</button></div>'
                ) % (esc(self.t("view.grid")), esc(self.t("view.timeline")))

    def filter_row(self, name, options, label_key=None):
        """一行筛选按钮。name 同时决定卡片上的 data-f-<name> 属性名。"""
        chips = []
        for i, (val, label) in enumerate(options):
            chips.append('<button class="chip-btn%s" data-value="%s">%s</button>'
                         % (" on" if i == 0 else "", esc(val), esc(label)))
        return ('<div class="filter-row" data-filter="%s"><span class="filter-label">%s</span>%s</div>'
                % (esc(name), esc(self.t(label_key or ("filter.%s" % name))), "".join(chips)))

    # ---- 筛选项来源 ----
    def year_options(self, items):
        years = sorted({fmt_date(i.get("publishedAt"))[:4] for i in items
                        if fmt_date(i.get("publishedAt"))}, reverse=True)
        return [("", self.t("filter.all"))] + [(y, y) for y in years]

    def coll_options(self, items):
        names = []
        for i in items:
            for c in i.get("collections") or []:
                if c and c not in names:
                    names.append(c)
        opts = [("", self.t("filter.all"))] + [(n, n) for n in names]
        if any(not (i.get("collections") or []) for i in items):
            opts.append(("__none__", self.t("filter.other")))
        return opts

    def album_options(self, items):
        names = []
        for i in items:
            a = (i.get("extra") or {}).get("album")
            if a and a not in names:
                names.append(a)
        opts = [("", self.t("filter.all"))] + [(n, n) for n in names]
        return opts

    def more_button(self, show, total):
        """就地展开更多（不跳页）。用次要样式，和下面的跳转按钮区分开。"""
        if total <= show:
            return ""
        return ('<div class="more-row"><button class="pill-link ghost" data-more-btn="%d">'
                '<span data-more-label>%s</span>'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>'
                "</button></div>") % (show, esc(self.t("more.expand")))

    def more_link(self, page):
        """跳转到该内容的独立页面。文案带上下文的宾语，避免和上面的展开按钮混淆。"""
        return ('<div class="more-row more-goto">'
                '<a class="pill-link primary arrow" href="%s">%s'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>'
                "</a></div>") % (self.url(page), esc(self.t("more.all.%s" % page)))

    def section(self, key, cards, cls="", sub="", reveal=0, right="", sortable="",
                filters="", filterable="", tail=""):
        anchor = key
        head = ('<div class="section-head"><h2>%s</h2>%s%s</div>'
                % (esc(self.t("section.%s" % key)),
                   '<span class="sub">%s</span>' % esc(sub) if sub else "", right))
        attr = ""
        if reveal:
            attr += ' data-reveal="%d"' % reveal
        if sortable:
            attr += ' data-sortable="%s"' % sortable
        if filterable:
            attr += ' data-filterable="%s"' % filterable
        empty = ('<p class="filter-empty is-hidden" data-empty-for="%s">%s</p>'
                 % (esc(filterable), esc(self.t("filter.none")))) if filterable else ""
        return ('<section class="section" id="%s"><div class="wrap">%s%s'
                '<div class="grid %s"%s>%s</div>%s%s%s</div></section>'
                % (anchor, head, filters, cls, attr, "".join(cards),
                   self.more_button(reveal, len(cards)) if reveal else "", empty, tail))

    # ---------- 页面外壳 ----------
    def url(self, page):
        """首页在根目录（zh-CN）或各自语言目录下，所以指向首页要用目录路径而非空串。"""
        if page == "index":
            return self.prefix or "./"
        return self.prefix + page + ".html"

    @staticmethod
    def locale_url(prefix, sub, page):
        base = prefix + (sub + "/" if sub else "")
        if page == "index":
            return base or "./"
        return base + page + ".html"

    def shell(self, page, title, body, head_extra=""):
        nav = "".join('<a href="%s"%s>%s</a>'
                      % (self.url(p), ' class="on"' if p == page else "", esc(self.t(k)))
                      for p, k in NAV)
        lang_items = []
        for code, label, sub in LOCALES:
            href = self.locale_url(self.prefix, sub, page)
            lang_items.append('<a class="lang-item%s" href="%s" hreflang="%s"><span>%s</span></a>'
                              % (" is-active" if code == self.locale else "", esc(href), code, esc(label)))
        status = []
        for p, s in (self.snap.get("platformStatus") or {}).items():
            cls = "pstat" if s.get("ok") else "pstat stale"
            status.append('<span class="%s"><i></i>%s %s · %s</span>'
                          % (cls, esc(PLATFORM_SHORT.get(p, p)),
                             esc(self.t("status.ok") if s.get("ok") else self.t("status.stale")),
                             esc(str(s.get("itemCount")))))

        # 分享卡片与规范链接：og:image 必须是绝对地址，所以要用 site.url
        base = (self.cfg["site"].get("url") or "").rstrip("/")
        og_page = page if page in ("index", "videos", "music", "articles", "projects", "about", "stats") else "index"
        # 注意：分享卡片与封面一样放在共享的 assets/og 下（不随语言复制），所以 URL 不带语言子目录
        og_rel = "assets/og/%s-%s.jpg" % (self.locale, og_page)
        og_url = ("%s/%s" % (base, og_rel)) if base else og_rel
        page_path = "" if page == "index" else page + ".html"
        canon = ("%s/%s%s" % (base, (self.sub + "/") if self.sub else "", page_path)) if base else ""
        alts = "".join('<link rel="alternate" hreflang="%s" href="%s/%s%s">'
                       % (code, base, (sub + "/") if sub else "", page_path) for code, _, sub in LOCALES) if base else ""

        # 首访语言自动判断：只注入到「根路径」（简中首页），避免用户手动进入某语言页后被弹走
        detect = ""
        ld = self.cfg.get("localeDetect") or {}
        if ld.get("enable") and self.locale == "zh-CN" and page == "index":
            # 注意：<script> 里不能用 HTML 转义，必须用 JSON 编码保证是合法 JS 字面量
            js = lambda v: json.dumps(v, ensure_ascii=False).replace("<", "\\u003c")  # noqa: E731
            detect = DETECT_SCRIPT % {
                "regions": js(ld.get("regions") or {}),
                "geoip": js(ld.get("geoipEndpoint") or ""),
                "default": js(self.cfg["site"]["defaultLocale"]),
            }

        # 播放器配置
        pl = self.cfg.get("player") or {}
        player_cfg = json.dumps({"ownAudio": bool(pl.get("ownAudio", True))},
                                ensure_ascii=False, separators=(",", ":"))
        # 歌词字体是可选的：这几首歌的歌词里吴语方言字、拼音标注很多，
        # 用霞鹜文楷单独切一份要 600KB 左右（只在点开播放器时才下载）。
        # 关掉就把歌词回落到主字体 + 系统字体，省掉这个按需体积。
        if not pl.get("lyricFont", True):
            head_extra = ('<style>.op-lyrics,.op-line,.op-txt,.op-tr{font-family:var(--font)!important}</style>'
                          + head_extra)

        import hashlib as _h
        _js_path = os.path.join(SRC, "scripts", "app.js")
        asset_v = _h.sha256(open(_js_path, "rb").read()).hexdigest()[:10] if os.path.exists(_js_path) else "1"
        # 构建标识：前端会把它挂到 <html data-build> 并打进 console，便于确认浏览器跑的是哪一版
        build_id = time.strftime("%m%d-%H%M") + "-" + asset_v

        return SHELL % {
            "lang": esc(self.locale), "prefix": self.prefix, "title": esc(title),
            "asset_v": asset_v, "build_id": build_id,
            "desc": esc(self.t("site.desc")), "brand": esc(self.t("site.name")),
            "nav": nav, "lang_btn": esc(self.t("lang.current")),
            "lang_menu": "".join(lang_items), "search_url": self.url("search"),
            "home": self.url("index"), "body": body, "detect": detect,
            "head_extra": head_extra,
            "og_url": esc(og_url), "canonical": esc(canon), "alt_links": alts,
            "site_url": esc(base), "locale": esc(self.locale), "page_key": esc(page),
            "player_cfg": player_cfg,
            "bgm_wu": json.dumps([i["nativeId"].replace("song","") for i in self.wuyue_music_items(20)], ensure_ascii=False),
            "footer_updated": esc("%s %s" % (self.t("footer.updated"),
                                             fmt_date(self.snap.get("generatedAt")))),
            "footer_note": esc(self.t("footer.generated")), "footer_status": "".join(status),
            "i18n_json": json.dumps({self.locale: self.strings}, ensure_ascii=False,
                                    separators=(",", ":")),
        }

    # ---------- 各页正文 ----------
    def hero(self):
        d = self.data()
        bili, github, netease = (self.profiles.get(k) or {} for k in ("bilibili", "github", "netease"))
        avatar = bili.get("avatarLocal") or github.get("avatarLocal") or ""
        name = bili.get("name") or github.get("name") or self.cfg["site"]["owner"]
        bio = self.curated.get("intro") or bili.get("bio") or ""
        stats = []
        if (bili.get("stats") or {}).get("followers"):
            stats.append((fmt_num(bili["stats"]["followers"]), self.t("unit.fans")))
        stats += [(str(len(d["videos"])), self.t("unit.videos")),
                  (str(len(d["articleLists"])), self.t("unit.collections")),
                  (str(len(d["projects"])), self.t("unit.projects")),
                  (str(len(d["songs"])), self.t("unit.tracks"))]
        stat_html = "".join('<div class="stat"><b>%s</b><span>%s</span></div>' % (esc(v), esc(k))
                            for v, k in stats)
        # 用户要求注明：这些是「本站已收录」的数量，不是平台全量
        hero_note = ('<p class="hero-note">%s</p>' % esc(self.t("hero.note"))
                     if "hero.note" in self.strings else "")
        links = []
        if bili.get("url"):
            links.append('<a class="pill-link primary" href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                         % (esc(bili["url"]), esc(self.t("hero.enter"))))
        if netease.get("url"):
            links.append('<a class="pill-link" href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                         % (esc(netease["url"]), esc(self.t("hero.music"))))
        if github.get("url"):
            links.append('<a class="pill-link" href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                         % (esc(github["url"]), esc(self.t("hero.github"))))
        return ('<section class="hero"><div class="wrap"><div class="hero-in rise">'
                '<img class="avatar" src="%s%s" alt="%s">'
                '<div class="hero-body"><h1>%s</h1><p class="hero-bio">%s</p>'
                '<div class="hero-stats">%s</div>%s<div class="hero-links">%s</div></div>'
                "</div></div></section>"
                ) % (self.prefix, esc(avatar), esc(name), esc(name), esc(bio), stat_html,
                     hero_note, "".join(links))

    def wuyue_items(self, limit):
        """精选吴语视频：取指定视频合集（默认「吴越春秋」）内的视频，按播放量从高到低。

        来源通过 config/site.json 的 featured.wuSource 配置（按合集标题匹配），
        想换成别的合集或别人账号的合集，改配置即可，不用动代码。
        """
        name = (self.cfg.get("featured") or {}).get("wuSource") or "吴越春秋"
        index = {i["id"]: i for i in self.data()["videos"]}
        for c in self.collections:
            if (c.get("extra") or {}).get("kind") != "season":
                continue
            if (c.get("title") or "").strip() != name:
                continue
            items = [index[i] for i in (c.get("memberIds") or []) if i in index]
            items.sort(key=lambda i: ((i.get("stats") or {}).get("play") or 0), reverse=True)
            return items[:limit], c
        return [], None

    def feat_col(self, title, minis, source_key=None, href=None, sub=None, scroll=True):
        """精选区的一栏。

        scroll=True  → 可向下拉的榜单（默认露 initialItems 条，最多 maxItems 条），
                       带「向下拉」提示，跟随排序的栏还要带 data-top3 让前端实时刷新。
        scroll=False → 固定内容，不滚动、不加下拉提示（例如人工指定的精选项目）。
        """
        cfg = self.cfg.get("featured") or {}
        limit = int(cfg.get("maxItems") or 20)
        show = int(cfg.get("initialItems") or 3)
        head_extra = ('<a class="mini-more" href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                      % (esc(href), esc(self.t("section.more")))) if href else ""
        attr = (' data-top3="%s" data-top3-limit="%d"' % (source_key, limit)) if source_key else ""
        if scroll:
            max_h = show * 66 + (show - 1) * 10 + 2
            body = ('<div class="mini-list scroll"%s style="max-height:%dpx">%s</div>'
                    '<p class="mini-hint">%s</p>'
                    % (attr, max_h, "".join(minis),
                       esc(self.t("feat.pull").replace("{n}", str(limit)))))
        else:
            body = '<div class="mini-list">%s</div>' % "".join(minis)
        return ('<div class="feat-col"><div class="subsection-head"><h3>%s</h3>'
                '<span class="sub">%s</span>%s</div>%s</div>'
                ) % (esc(title), esc(sub or self.t("feat.top20")), head_extra, body)

    def wuyue_music_items(self, limit=20):
        """精选吴语音乐：站内所有标题含「吴语 / 吳語」的音乐，按投稿时间倒序，取前 limit 条。

        随构建自动刷新（新收录的吴语音乐会自动进榜；榜单来自快照，所以每次重建都会重算。
        """
        keys = ("吴语", "吳語")
        items = []
        for i in self.data()["songs"]:
            hay = " ".join([(i.get("title") or ""), " ".join(i.get("tags") or []),
                            ((i.get("extra") or {}).get("album") or "")
                            ])
            if any(k in hay for k in keys):
                items.append(i)
        items.sort(key=lambda i: (i.get("publishedAt") or ""), reverse=True)
        return items[:limit]

    def fixed_project_items(self):
        """精选项目栏：按配置里写死的仓库顺序取（人工指定，不随排序变化）。"""
        names = (self.cfg.get("featured") or {}).get("fixedProjects") or []
        if not names:
            return []
        index = {}
        for it in self.data()["projects"]:
            full = (it.get("extra") or {}).get("fullName") or it["title"]
            index[full] = it
        out, miss = [], []
        for n in names:
            if n in index:
                out.append(index[n])
            else:
                miss.append(n)
        if miss:
            print("    ! 精选项目里这几个仓库没在快照中找到：%s" % ", ".join(miss))
        return out

    def mini_project(self, it):
        """项目用竖排小卡片：没有封面图，就用名字 + 描述 + 语言/星标/更新时间。"""
        ex = it.get("extra") or {}
        lang = (it.get("tags") or [None])[0]
        stars = (it.get("stats") or {}).get("stars") or 0
        bits = []
        if lang:
            bits.append(lang)
        bits.append("★ %s" % fmt_num(stars))
        d = fmt_date(it.get("publishedAt"))
        if d:
            bits.append(d)
        return ('<a class="mini mini-plain" href="%s" target="_blank" rel="noopener noreferrer">'
                '<span class="mini-body"><span class="mini-title">%s</span>'
                '<span class="mini-meta">%s</span>'
                '%s</span></a>'
                ) % (esc(it["url"]), esc(it["title"]), esc(" · ".join(bits)),
                     ('<span class="mini-desc">%s</span>' % esc(it.get("description") or ""))
                     if it.get("description") else "")

    def featured_block(self):
        """首页精选：精选视频 / 精选音乐 / 精选吴语视频，各可下拉到前 20。

        跟随排序的那两栏，服务端只渲染 initialItems 条做首屏与无 JS 兜底，
        剩下的由前端按当前排序补齐到 maxItems（见 app.js 的 refreshTop3）。
        """
        d = self.data()
        cfg = self.cfg.get("featured") or {}
        limit = int(cfg.get("maxItems") or 20)
        show = int(cfg.get("initialItems") or 3)
        cols = []

        if d["videos"]:
            cols.append(self.feat_col(
                self.t("pin.videos"),
                [self.mini(v, i + 1) for i, v in enumerate(d["videos"][:show])],
                source_key="videos"))

        if d["songs"]:
            cols.append(self.feat_col(
                self.t("pin.music"),
                [self.mini(s, i + 1) for i, s in enumerate(d["songs"][:show])],
                source_key="songs"))

        wu, wc = self.wuyue_items(limit)
        if wu:
            cols.append(self.feat_col(
                self.t("pin.wuyue"),
                [self.mini(v, i + 1) for i, v in enumerate(wu)],
                href=(wc or {}).get("url"),
                sub="%s · %s" % (self.t("meta.play"), self.t("feat.top20"))))

        wm = self.wuyue_music_items(limit)
        if wm:
            cols.append(self.feat_col(
                self.t("featured.wuyue_music"),
                [self.mini(m, i + 1) for i, m in enumerate(wm)],
                sub=self.t("feat.fixed"), scroll=False))

        fixed = self.fixed_project_items()
        if fixed:
            cols.append(self.feat_col(
                self.t("pin.projects"),
                [self.mini_project(p) for p in fixed],
                sub=self.t("feat.fixed"), scroll=False))

        if not cols:
            return ""
        return ('<section class="section" id="featured"><div class="wrap">'
                '<div class="section-head"><h2>%s</h2><span class="sub">%s</span></div>'
                '<div class="featured-grid">%s</div></div></section>'
                % (esc(self.t("section.featured")), esc(self.t("section.featured.sub")),
                   "".join(cols)))

    def home_body(self):
        d = self.data()
        sec = [self.hero()]
        f = self.featured_block()
        if f:
            sec.append(f)

        # 预览列表放 24 条（首屏只露 12 条），这样精选栏的「前 20 名」在首页也能取满
        sec.append(self.section("videos",
                                [self.media_card(v, delay=min(i, 8) * 45) for i, v in enumerate(d["videos"][:24])],
                                cls="videos", sub="%d %s" % (len(d["videos"]), self.t("unit.videos")),
                                reveal=12, right=self.view_switch() + self.sortbar("videos"),
                                sortable="videos", filterable="videos",
                                filters=self.filter_row("year", self.year_options(d["videos"])),
                                tail=self.more_link("videos")))

        sec.append(self.section("music",
                                [self.media_card(s, square=True, delay=min(i, 8) * 45,
                                                 sub=(s.get("extra") or {}).get("album"))
                                 for i, s in enumerate(d["songs"][:24])],
                                cls="music", sub="%d %s" % (len(d["songs"]), self.t("unit.tracks")),
                                reveal=12, right=self.sortbar("songs"), sortable="songs",
                                filterable="songs",
                                filters=self.filter_row("album", self.album_options(d["songs"])),
                                tail=self.more_link("music")))

        sec.append(self.section("projects",
                                [self.project_card(p, delay=min(i, 6) * 50) for i, p in enumerate(d["projects"])],
                                cls="repos", sub="%d %s" % (len(d["projects"]), self.t("unit.projects"))))

        if d["articleLists"]:
            sec.append(self.section("articles",
                                    [self.collection_card(c, delay=min(i, 6) * 50)
                                     for i, c in enumerate(d["articleLists"])],
                                    cls="albums",
                                    sub="%d %s · %d %s" % (len(d["articleLists"]), self.t("unit.collections"),
                                                           len(d["posts"]), self.t("unit.articles")),
                                    tail='<div class="subsection-head" style="margin-top:32px"><h3>%s</h3>'
                                         '<span class="sub">%d %s</span></div>'
                                         '<div class="posts" data-reveal="8">%s</div>%s'
                                         % (esc(self.t("section.articles")), len(d["posts"]),
                                            esc(self.t("unit.articles")),
                                            "".join(self.post_row(p, delay=min(i, 6) * 40)
                                                    for i, p in enumerate(d["posts"][:8])),
                                            self.more_link("articles"))))
        return "\n".join(sec)

    def page_body(self, page):
        d = self.data()
        if page == "videos":
            return [self.section("videos",
                                 [self.media_card(v, delay=min(i, 10) * 30) for i, v in enumerate(d["videos"])],
                                 cls="videos", sub="%d %s" % (len(d["videos"]), self.t("unit.videos")),
                                 reveal=24, right=self.view_switch() + self.sortbar("videos"),
                                 sortable="videos", filterable="videos",
                                 filters=self.filter_row("year", self.year_options(d["videos"]))
                                         + self.filter_row("coll", self.coll_options(d["videos"]),
                                                           label_key="filter.collection"))]
        if page == "music":
            return [self.section("music",
                                 [self.media_card(s, square=True, delay=min(i, 10) * 30,
                                                  sub=(s.get("extra") or {}).get("album"))
                                  for i, s in enumerate(d["songs"])],
                                 cls="music", sub="%d %s" % (len(d["songs"]), self.t("unit.tracks")),
                                 reveal=24, right=self.sortbar("songs"), sortable="songs",
                                 filterable="songs",
                                 filters=self.filter_row("year", self.year_options(d["songs"]))
                                         + self.filter_row("album", self.album_options(d["songs"])))]
        if page == "projects":
            return [self.section("projects",
                                 [self.project_card(p, delay=min(i, 6) * 50) for i, p in enumerate(d["projects"])],
                                 cls="repos", sub="%d %s" % (len(d["projects"]), self.t("unit.projects")))]
        if page == "articles":
            out = []
            if d["articleLists"]:
                out.append(self.section("articles",
                                        [self.collection_card(c, delay=min(i, 6) * 50)
                                         for i, c in enumerate(d["articleLists"])],
                                        cls="albums",
                                        sub="%d %s" % (len(d["articleLists"]), self.t("unit.collections"))))
            out.append('<section class="section" id="posts"><div class="wrap">'
                       '<div class="section-head"><h2>%s</h2><span class="sub">%s</span></div>'
                       '<div class="posts" data-reveal="24">%s</div>%s</div></section>'
                       % (esc(self.t("section.articles")),
                          esc("%d %s" % (len(d["posts"]), self.t("unit.articles"))),
                          "".join(self.post_row(p, delay=min(i, 8) * 35) for i, p in enumerate(d["posts"])),
                          self.more_button(24, len(d["posts"]))))
            return out
        return []

    def about_body(self):
        d = self.data()
        about = self.curated.get("about") or {}
        prof = self.profiles
        bili, github, netease = (prof.get(k) or {} for k in ("bilibili", "github", "netease"))
        name = bili.get("name") or self.cfg["site"]["owner"]
        body = about.get("body") or bili.get("bio") or ""

        plat = []
        if bili.get("url"):
            plat.append('<a class="plat-card" href="%s" target="_blank" rel="noopener noreferrer">'
                        '<span><span class="pname">%s</span><br><span class="pdesc">%s %s</span></span></a>'
                        % (esc(bili["url"]), esc(PLATFORM_LABEL["bilibili"]),
                           fmt_num((bili.get("stats") or {}).get("followers")), esc(self.t("unit.fans"))))
        if netease.get("url"):
            plat.append('<a class="plat-card" href="%s" target="_blank" rel="noopener noreferrer">'
                        '<span><span class="pname">%s</span><br><span class="pdesc">%s %s</span></span></a>'
                        % (esc(netease["url"]), esc(PLATFORM_LABEL["netease"]),
                           len(d["songs"]), esc(self.t("unit.tracks"))))
        if github.get("url"):
            plat.append('<a class="plat-card" href="%s" target="_blank" rel="noopener noreferrer">'
                        '<span><span class="pname">%s</span><br><span class="pdesc">%s %s</span></span></a>'
                        % (esc(github["url"]), esc(PLATFORM_LABEL["github"]),
                           len(d["projects"]), esc(self.t("unit.projects"))))

        rows = [(len(d["videos"]), self.t("unit.videos")),
                (len(d["articleLists"]), self.t("unit.collections")),
                (len(d["posts"]), self.t("unit.articles")),
                (len(d["songs"]), self.t("unit.tracks")),
                (len(d["projects"]), self.t("unit.projects"))]
        stats = "".join('<div class="stat"><b>%s</b><span>%s</span></div>' % (esc(str(n)), esc(k))
                        for n, k in rows)
        return ('<section class="section"><div class="wrap">'
                '<div class="about-card rise"><h2 style="margin:0 0 10px;font-size:20px;font-weight:500;'
                'color:var(--blue-800)">%s</h2><p>%s</p></div>'
                '<div class="subsection-head" style="margin-top:30px"><h3>%s</h3></div>'
                '<div class="plat-grid">%s</div>'
                '<div class="subsection-head" style="margin-top:30px"><h3>%s</h3></div>'
                '<div class="hero-stats">%s</div></div></section>'
                ) % (esc(name), esc(body), esc(self.t("about.platforms")), "".join(plat),
                     esc(self.t("about.overview")), stats)

    def search_body(self):
        d = self.data()
        years = sorted({fmt_date(i.get("publishedAt"))[:4] for i in self.items
                        if fmt_date(i.get("publishedAt"))[:4]}, reverse=True)
        types = [("", self.t("search.allTypes")), ("video", self.t("nav.videos")),
                 ("audio", self.t("nav.music")), ("post", self.t("nav.articles")),
                 ("project", self.t("nav.projects"))]
        chips = "".join('<button class="chip-btn%s" data-value="%s">%s</button>'
                        % (" on" if not v else "", esc(v), esc(label)) for v, label in types)
        ychips = '<button class="chip-btn on" data-value="">%s</button>' % esc(self.t("search.allYears"))
        ychips += "".join('<button class="chip-btn" data-value="%s">%s</button>' % (y, y) for y in years)
        return ('<section class="section"><div class="wrap" id="search-page" data-index="%sassets/search-index.%s.json">'
                '<div class="searchbar"><input class="search-input" id="q" type="search" '
                'autocomplete="off" placeholder="%s"></div>'
                '<div class="filter-row" data-filter="type">%s</div>'
                '<div class="filter-row" data-filter="year">%s</div>'
                '<p class="search-note" id="search-note">%s</p>'
                '<div class="grid videos" id="search-results"></div></div></section>'
                ) % (esc(self.prefix), esc(self.locale), esc(self.t("search.placeholder")),
                     chips, ychips, esc(self.t("search.hint")))

    def stats_body(self):
        """数据统计页：全部数字由构建期快照算出，随每次更新自动重算。"""
        d = self.data()
        videos, songs, posts, projects = d["videos"], d["songs"], d["posts"], d["projects"]

        total_play = sum((v.get("stats") or {}).get("play") or 0 for v in videos)
        total_cmt = sum((s.get("stats") or {}).get("comments") or 0 for s in songs)
        total_sec = sum((v.get("durationSec") or 0) for v in videos) + \
                    sum((s.get("durationSec") or 0) for s in songs)
        years = sorted({fmt_date(i.get("publishedAt"))[:4] for i in videos + songs + posts
                        if fmt_date(i.get("publishedAt"))})
        total_items = len(videos) + len(songs) + len(posts) + len(projects)

        # 内容概览
        cards = [("%s" % len(videos), self.t("unit.videos")),
                 ("%s" % len(songs), self.t("unit.tracks")),
                 ("%s" % len(d["articleLists"]), self.t("unit.collections")),
                 ("%s" % len(projects), self.t("unit.projects")),
                 (fmt_num(total_play), self.t("stats.totalPlay")),
                 (fmt_num(total_cmt), self.t("stats.totalComments")),
                 ("%.0f" % (total_sec / 3600.0), self.t("stats.hours")),
                 ("%d" % len(years), self.t("stats.years"))]
        overview = "".join('<div class="stat"><b>%s</b><span>%s</span></div>' % (esc(v), esc(k))
                           for v, k in cards)

        # 年度发布趋势（纯 CSS 条形，不用图表库）
        per_year = {}
        for it in videos + songs + posts:
            y = fmt_date(it.get("publishedAt"))[:4]
            if y:
                per_year[y] = per_year.get(y, 0) + 1
        peak = max(per_year.values()) if per_year else 1
        bars = ""
        for y in sorted(per_year, reverse=True):
            n = per_year[y]
            bars += ('<div class="bar-row"><span class="bar-year">%s</span>'
                     '<span class="bar-track"><span class="bar-fill" style="width:%.1f%%"></span></span>'
                     '<span class="bar-num">%d</span></div>') % (esc(y), n * 100.0 / peak, n)

        # 分类排行：播放最多 / 评论最多
        top_v = [self.mini(v, i + 1) for i, v in enumerate(videos[:10])]
        top_s = [self.mini(s, i + 1) for i, s in enumerate(songs[:10])]

        # 平台分布
        plats = {}
        for it in self.items:
            if (it.get("extra") or {}).get("isAlbum"):
                continue
            plats[it["platform"]] = plats.get(it["platform"], 0) + 1
        ptot = sum(plats.values()) or 1
        ptw = ""
        for p, n in sorted(plats.items(), key=lambda kv: -kv[1]):
            ptw += ('<div class="bar-row"><span class="bar-year">%s</span>'
                    '<span class="bar-track"><span class="bar-fill alt" style="width:%.1f%%"></span></span>'
                    '<span class="bar-num">%d</span></div>') % (esc(PLATFORM_LABEL.get(p, p)),
                                                                n * 100.0 / ptot, n)

        return ('<section class="section"><div class="wrap">'
                '<div class="subsection-head"><h3>%s</h3><span class="sub">%s</span></div>'
                '<div class="hero-stats">%s</div>'
                '<p class="stat-note">%s</p>'
                '<div class="subsection-head" style="margin-top:34px"><h3>%s</h3></div>%s'
                '<div class="subsection-head" style="margin-top:34px"><h3>%s</h3></div>%s'
                '<div class="stat-cols">'
                '<div><div class="subsection-head"><h3>%s</h3></div><div class="mini-list">%s</div></div>'
                '<div><div class="subsection-head"><h3>%s</h3></div><div class="mini-list">%s</div></div>'
                "</div></div></section>"
                ) % (esc(self.t("stats.overview")), esc("%s %d" % (self.t("stats.items"), total_items)),
                     overview, esc(self.t("stats.note")),
                     esc(self.t("stats.trend")), bars,
                     esc(self.t("stats.platforms")), ptw,
                     esc(self.t("stats.topVideos")), "".join(top_v),
                     esc(self.t("stats.topSongs")), "".join(top_s))

    # ---------- 搜索索引 ----------
    def search_index(self):
        d = self.data()
        out = []
        for it in self.items:
            if it["id"] in self.hidden:
                continue
            # 专辑条目只是歌曲的元数据来源，页面上已不再作为独立条目展示，
            # 所以不进搜索索引；专辑名通过歌曲的 extra.album 参与检索。
            if (it.get("extra") or {}).get("isAlbum"):
                continue
            st = it.get("stats") or {}
            kind = it["type"]
            ex = it.get("extra") or {}
            heat = st.get("comments") if kind == "audio" else st.get("play")
            if kind == "post":
                heat = st.get("view")
            if kind == "project":
                heat = st.get("stars")
            bits = []
            if kind == "project" and (it.get("tags") or [None])[0]:
                bits.append(it["tags"][0])
            if heat:
                key = {"video": "meta.play", "audio": "meta.comments",
                       "post": "meta.view", "project": "meta.heat"}.get(kind, "meta.heat")
                bits.append("%s %s" % (fmt_num(heat), self.t(key)))
            dt = fmt_date(it.get("publishedAt"))
            if dt:
                bits.append(dt)
            cover = it.get("cover")
            embed = ""
            if kind == "audio":
                embed = (it.get("embed") or {}).get("src", "")
            elif kind == "video":
                embed = bili_embed((it.get("embed") or {}).get("bvid") or it["nativeId"],
                                   (it.get("embed") or {}).get("cid"))
            extra = ex.get("album") or ((it.get("collections") or [None])[0] if kind == "post" else None) or ""
            # 检索用的字段：标题 + 专辑/文集名 + 标签 + 描述摘要。
            # 注意描述只进检索、不上屏，所以不放进索引的展示字段里，
            # 否则会把字体子集撑大一圈（字体是按上屏用字切的）。
            hay = " ".join([it.get("title") or "", extra or "",
                            " ".join(it.get("tags") or []),
                            " ".join(it.get("collections") or []),
                            (it.get("description") or "")[:120]])
            out.append({
                "i": it["id"], "t": it.get("title") or "", "k": kind, "pl": it["platform"],
                "u": it.get("url") or "", "c": (self.prefix + cover) if cover else "",
                "e": embed, "x": extra, "d": dt, "h": int(heat or 0),
                "l": self.t("player.openSourceAudio" if kind == "audio" else "player.openSource"),
                "m": " · ".join(bits),
                "s": hay.lower(),
            })
        return out

    # ---------- 输出 ----------
    def page_head(self, page):
        """子页面顶部：面包屑 + 大标题。"""
        crumb = ('<div class="wrap"><a class="crumb" href="%s">← %s</a></div>'
                 % (self.url("index"), esc(self.t("crumb.home"))))
        if page in ("videos", "music", "projects", "articles"):
            title, sub = self.t("nav.%s" % page), self.t("section.%s.sub" % page)
        elif page == "search":
            title, sub = self.t("search.title"), self.t("search.sub")
        elif page == "stats":
            title, sub = self.t("stats.title"), self.t("stats.sub")
        elif page == "about":
            title, sub = self.t("about.title"), self.t("site.tagline")
        else:
            return ""
        return crumb + '<div class="wrap page-head"><h1>%s</h1><span class="sub">%s</span></div>' % (
            esc(title), esc(sub))

    def write(self):
        os.makedirs(self.out_dir(), exist_ok=True)
        out = []
        for page in PAGES:
            if page == "index":
                body = self.home_body()
                title = self.t("site.name")
            elif page == "search":
                body = self.search_body()
                title = "%s · %s" % (self.t("search.title"), self.t("site.name"))
            elif page == "about":
                body = self.about_body()
                title = "%s · %s" % (self.t("about.title"), self.t("site.name"))
            elif page == "stats":
                body = self.stats_body()
                title = "%s · %s" % (self.t("stats.title"), self.t("site.name"))
            else:
                body = "".join(self.page_body(page))
                title = "%s · %s" % (self.t("nav.%s" % page), self.t("site.name"))
            body = self.page_head(page) + body
            p = os.path.join(self.out_dir(), page + ".html")
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.shell(page, title, body))
            out.append(p)

        idx = os.path.join(DIST, "assets", "search-index.%s.json" % self.locale)
        os.makedirs(os.path.dirname(idx), exist_ok=True)
        with open(idx, "w", encoding="utf-8") as f:
            json.dump(self.search_index(), f, ensure_ascii=False, separators=(",", ":"))
        return out

    def out_dir(self):
        return DIST if not self.sub else os.path.join(DIST, self.sub)


SHELL = """<!DOCTYPE html>
<html lang="%(lang)s">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
%(detect)s
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<meta property="og:type" content="website">
<meta property="og:site_name" content="%(brand)s">
<meta property="og:title" content="%(title)s">
<meta property="og:description" content="%(desc)s">
<meta property="og:image" content="%(og_url)s">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="%(locale)s">
<meta property="og:url" content="%(canonical)s">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="%(title)s">
<meta name="twitter:description" content="%(desc)s">
<meta name="twitter:image" content="%(og_url)s">
<link rel="canonical" href="%(canonical)s">
%(alt_links)s
<link rel="icon" href="data:image/svg+xml,%%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%%3E%%3Ccircle cx='16' cy='16' r='13' fill='%%232980b9'/%%3E%%3Ccircle cx='21' cy='11' r='4' fill='%%233fb6a8'/%%3E%%3C/svg%%3E">
<link rel="stylesheet" href="%(prefix)sassets/css/main.css?v=%(asset_v)s">
%(head_extra)s
</head>
<body>
<div class="loadbar" id="loadbar"><span></span></div>

<header class="topbar">
  <div class="wrap topbar-in">
    <a class="brand" href="%(home)s"><span class="brand-dot"></span>%(brand)s</a>
    <nav class="nav">%(nav)s</nav>
    <a class="icon-btn" href="%(search_url)s" aria-label="search">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>
      </svg>
    </a>
    <button class="icon-btn bgm-btn" id="bgm-btn" type="button" title="BGM">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 18V5l12-2v13"/>
        <circle cx="6" cy="18" r="3"/>
        <circle cx="18" cy="16" r="3"/>
      </svg>
    </button>
    <div class="lang">
      <button class="lang-btn" id="lang-btn">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 3 2.5 15 0 18M12 3c-2.5 3-2.5 15 0 18"/>
        </svg>
        <span>%(lang_btn)s</span>
      </button>
      <div class="lang-menu" id="lang-menu">%(lang_menu)s</div>
    </div>
  </div>
</header>

<main>
%(body)s
</main>

<footer>
  <div class="wrap foot-in">
    <span>%(footer_updated)s</span>
    <span>%(footer_note)s</span>
    <div class="foot-status">%(footer_status)s</div>
  </div>
</footer>

<div class="modal-mask" id="modal">
  <div class="modal" role="dialog" aria-modal="true">
    <div class="modal-head">
      <div><h3 id="m-title"></h3><div class="mmeta" id="m-meta"></div></div>
      <button class="modal-close" aria-label="close">&times;</button>
    </div>
    <div class="modal-stage" id="m-stage"></div>
    <div class="modal-foot" id="m-foot"></div>
  </div>
</div>

<div class="bgm-panel" id="bgm-panel" role="dialog" aria-modal="false" aria-label="BGM playlist">
  <div class="bgp-head">
    <span class="bgp-title" id="bgp-title">BGM</span>
    <button class="bgp-x" id="bgm-close" type="button" aria-label="close">&times;</button>
  </div>
  <p class="bgp-hint" id="bgp-hint"></p>
  <ul class="bgm-list" id="bgm-list"></ul>
  <div class="bgp-bar">
    <span class="bgp-now" id="bgm-now"></span>
    <span class="op-seek" id="bgm-seek">
      <span class="op-track"><span class="op-fill" id="bgm-fill"></span></span>
      <span class="op-knob" id="bgm-knob"></span>
    </span>
    <div class="bgp-btns">
      <button class="op-btn" id="bgm-prev" type="button" aria-label="prev"><svg viewBox="0 0 24 24"><path d="M6 6h2v12H6zM20 6v12l-9-6z"/></svg></button>
      <button class="op-btn main" id="bgm-toggle" type="button" aria-label="play">&#9654;</button>
      <button class="op-btn" id="bgm-next" type="button" aria-label="next"><svg viewBox="0 0 24 24"><path d="M16 6h2v12h-2zM4 6l9 6-9 6z"/></svg></button>
      <button class="op-btn wide" id="bgm-mode" type="button" title="mode"></button>
      <button class="op-btn" id="bgm-off" type="button" title="on/off">&#9211;</button>
    </div>
  </div>
</div>

<div class="share-modal" id="share-modal" role="dialog" aria-modal="true">
  <div class="sm-box">
    <div class="sm-head">
      <span id="sm-title"></span>
      <button class="sm-x" id="share-x" type="button" aria-label="close">&times;</button>
    </div>
    <img id="share-img" alt="">
    <p class="sm-hint" id="sm-hint"></p>
    <a class="pill-link primary" id="share-dl" download></a>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>window.SYS_I18N=%(i18n_json)s;window.SYS_LOCALE="%(lang)s";window.SYS_PREFIX="%(prefix)s";window.SYS_PLAYER=%(player_cfg)s;window.SYS_BGM_WU=%(bgm_wu)s;window.SYS_BUILD="%(build_id)s";</script>
<script src="%(prefix)sassets/js/app.js?v=%(asset_v)s"></script>
</body>
</html>
"""

# 首访语言自动判断。做成内联脚本放在 <head>，在渲染前就决策，避免先闪一下中文再跳走。
# 优先级：用户手选过 > 浏览器语言（中文/日文可立即判定，零网络请求） > IP 归属地 > 英文兜底。
DETECT_SCRIPT = """<script>(function(){
var REGIONS=%(regions)s, GEOIP=%(geoip)s, DEFAULT=%(default)s;
var SUB={"zh-CN":"","zh-TW":"zh-TW/","en":"en/","ja":"ja/"};
var HERE="zh-CN";
function saved(){try{return localStorage.getItem("sys-locale");}catch(e){return null;}}
function remember(v){try{localStorage.setItem("sys-locale",v);}catch(e){}}
function go(target){
  if(!target||target===HERE||!(target in SUB))return;
  var path=location.pathname;
  if(path.indexOf("zh-TW/")>=0||path.indexOf("en/")>=0||path.indexOf("ja/")>=0)return;
  var prefix=SUB[target];
  location.replace(path.replace(/[^/]*$/,prefix)+location.hash);
}
var pick=saved();
if(pick&&(pick in SUB)){go(pick);return;}
var langs=(navigator.languages&&navigator.languages.length?navigator.languages:[navigator.language||""]).map(function(s){return String(s||"").toLowerCase();});
for(var i=0;i<langs.length;i++){
  var l=langs[i];
  if(/^zh(-|$)/.test(l)){
    if(/hant|tw|hk|mo/.test(l)){go("zh-TW");}else{go("zh-CN");}
    return;
  }
  if(/^ja(-|$)/.test(l)){go("ja");return;}
}
if(!GEOIP){go("en");return;}
var done=false;
function byGeo(c){if(done)return;done=true;for(var k in REGIONS){if((REGIONS[k]||[]).indexOf(c)>=0){go(k);return;}}go("en");}
try{
  var x=new XMLHttpRequest();
  x.open("GET",GEOIP,true);x.timeout=1500;
  x.onload=function(){try{byGeo((JSON.parse(x.responseText).country||"").toUpperCase());}catch(e){byGeo("");}};
  x.onerror=x.ontimeout=function(){byGeo("");};
  x.send();
}catch(e){byGeo("");}
})();</script>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--clean", action="store_true", help="先清空 dist（本机沙箱下很慢）")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    print("== 渲染站点 ==")
    t0 = time.time()
    shared = {
        "cfg": load_json(CONFIG),
        "snap": load_json(SNAPSHOT, {}) or {},
        "curated": load_json(CURATED, {}) or {},
        "i18n": {c: (load_json(os.path.join(SRC, "i18n", c + ".json"), {}) or {})
                 for c, _, _ in LOCALES},
    }
    if not shared["snap"].get("items"):
        print("  ! 快照为空，请先运行 collect_all.py")
        return 1

    os.makedirs(DIST, exist_ok=True)
    if args.clean:
        print("  清空 dist …")
        clean_dir(DIST)

    per_locale = []
    for code, label, _ in LOCALES:
        files = Builder(code, shared).write()
        per_locale.append((label, files))

    os.makedirs(os.path.join(DIST, "assets"), exist_ok=True)
    for src_sub, dist_sub in (("styles", "css"), ("scripts", "js")):
        s = os.path.join(SRC, src_sub)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(DIST, "assets", dist_sub), dirs_exist_ok=True)
    for sub in ("covers", "avatars", "fonts", "img", "og"):
        s = os.path.join(SRC, "assets", sub)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(DIST, "assets", sub), dirs_exist_ok=True)

    # 字体缓存破版：文件名不变，浏览器（尤其是手机）会一直用旧字体，
    # 导致哪怕字体里已经补上假名，用户看到的还是旧版。用文件哈希做查询串。
    try:
        css_path = os.path.join(DIST, "assets", "css", "main.css")
        css = open(css_path, "r", encoding="utf-8").read()
        fonts_dir = os.path.join(SRC, "assets", "fonts")
        if os.path.isdir(fonts_dir):
            for font in sorted(os.listdir(fonts_dir)):
                if not font.endswith(".woff2"):
                    continue
                h = hashlib.sha256(open(os.path.join(fonts_dir, font), "rb").read()).hexdigest()[:10]
                css = css.replace("../fonts/" + font, "../fonts/%s?v=%s" % (font, h))
        open(css_path, "w", encoding="utf-8").write(css)
        print("  字体缓存破版已应用（woff2 查询串带哈希）")
    except Exception as exc:  # noqa: BLE001
        print("  ! 字体缓存破版跳过：%s" % exc)

    # 分享卡用的二维码：构建期生成，运行时只管拼图
    qr_dir = os.path.join(DIST, "assets", "qr")
    os.makedirs(qr_dir, exist_ok=True)
    qr_count = 0
    if segno is not None:
        for it in (shared["snap"].get("items") or []):
            url = it.get("url") or ""
            if not url:
                continue
            if (it.get("extra") or {}).get("isAlbum"):
                continue
            name = "%s-%s.png" % (it["platform"], re.sub(r"[^A-Za-z0-9_.-]", "_", str(it["nativeId"]))[:60])
            try:
                segno.make(url, error="m").save(os.path.join(qr_dir, name), scale=4, border=1)
                qr_count += 1
            except Exception:  # noqa: BLE001
                continue
        print("  二维码 %d 张" % qr_count)
    else:
        print("  ! 未安装 segno，跳过二维码生成（分享卡将不带二维码）")

    # BGM 用的曲目元数据（构建期生成，运行时按 id 查表；避免前端到处扫描 DOM）
    try:
        bgm = {}
        for it in (shared["snap"].get("items") or []):
            if it.get("type") != "audio":
                continue
            if (it.get("extra") or {}).get("isAlbum"):
                continue
            sid = str((it.get("embed") or {}).get("songId") or "")
            if not sid:
                continue
            cover = it.get("cover")
            bgm[sid] = {"t": it.get("title") or "", "c": cover or "", "a": ((it.get("extra") or {}).get("album") or "")
            }
        open(os.path.join(DIST, "assets", "bgm-meta.json"), "w", encoding="utf-8").write(json.dumps(bgm, ensure_ascii=False, separators=(",", ":")))
        print("  BGM 曲目表 %d 首" % len(bgm))
    except Exception as exc:  # noqa: BLE001
        print("  ! BGM 曲目表生成失败：%s" % exc)

        # CSS / JS 也加缓存破版（同字体，防止浏览器用旧版导致新功能全部失效）
        for asset_sub, ext in (("css", "css"), ("js", "js")):
            ap = os.path.join(DIST, "assets", asset_sub)
            if not os.path.isdir(ap):
                continue
            for f in os.listdir(ap):
                if not f.endswith("." + ext):
                    continue
                fp = os.path.join(ap, f)
                h = hashlib.sha256(open(fp, "rb").read()).hexdigest()[:10]
                # 只替换 HTML 里的引用
                for page in glob.glob(os.path.join(DIST, "**", "*.html"), recursive=True):
                    pt = open(page, "r", encoding="utf-8").read()
                    nt = pt.replace("assets/%s/%s" % (asset_sub, f),
                                    "assets/%s/%s?v=%s" % (asset_sub, f, h))
                    if nt != pt:
                        open(page, "w", encoding="utf-8").write(nt)

    shutil.copy(SNAPSHOT, os.path.join(DIST, "snapshot.json"))
    with open(os.path.join(DIST, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("User-agent: *\nAllow: /\n")

    # 播放器运行时数据（多档音频直链 + 动态歌词），独立成一个文件按需加载，
    # 不塞进页面，避免四个语言版本各背一份。
    player = shared["snap"].get("player") or {}
    pd = {k: v for k, v in player.items() if v.get("q") or v.get("l")}
    # 构建时间戳：前端据此判断「签名直链是否还新鲜」，过期就改用不过期的对外入口。
    # 用 dict 包一层，避免污染按 songId 遍历的地方（如字体子集脚本）。
    pd["__build"] = {"ts": int(time.time())}
    with open(os.path.join(DIST, "assets", "player-data.json"), "w", encoding="utf-8") as f:
        json.dump(pd, f, ensure_ascii=False, separators=(",", ":"))
    psz = os.path.getsize(os.path.join(DIST, "assets", "player-data.json"))
    songs = {k: v for k, v in pd.items() if k != "__build"}
    print("  播放器数据：%d 首，%.0f KB（直链 %d 首 / 歌词 %d 首）"
          % (len(songs), psz / 1024,
             sum(1 for v in songs.values() if v.get("q")),
             sum(1 for v in songs.values() if v.get("l"))))

    total = nfiles = 0
    for dp, dn, fn in os.walk(DIST):
        for f2 in fn:
            total += os.path.getsize(os.path.join(dp, f2))
            nfiles += 1

    print("  每种语言 %d 个页面：" % len(PAGES))
    first_label, first_files = per_locale[0]
    for p in first_files:
        print("    %-46s %5.0f KB" % (os.path.relpath(p, DIST), os.path.getsize(p) / 1024))
    print("  语言：%s" % "、".join(l for l, _ in per_locale))
    print("  构建完成：%d 个文件，共 %.1f MB，用时 %.1fs"
          % (nfiles, total / 1048576, time.time() - t0))

    if args.serve:
        import functools
        import http.server
        import socketserver
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIST)
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
            print("  预览：http://127.0.0.1:%d/" % args.port)
            httpd.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
