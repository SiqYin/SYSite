"""字体子集化：把 25 MB 的霞鹜文楷 Regular 按「用字场景」切成多份 woff2。

为什么要这么切
--------------
霞鹜文楷 Regular 覆盖 4.6 万个码位（CJK 基本区 20992 字 + 扩展 A 6592 字全部在内）。
整份做成一个 woff2 约 5~6 MB，手机首屏背不动；但只按「当前用字」切，
新投稿带来的新字、歌词里的方言/生僻字就会回落系统字体
——「一部分汉字套了霞鹜文楷、一部分没套」就是这么来的。

所以切成三层，靠 CSS 字体族的**逐字回退**顺序让浏览器按需下载：

  A  content  首屏一定会出现的字（页面 HTML/CSS/JS + 四语文案 + BGM 曲名）
              永远加载，约 350 KB；
  B  lyrics   歌词 + 站内检索索引里的字（不上首屏）
              只在打开播放器 / 用搜索时才下载；
  C  ext-N    霞鹜文楷里其余**全部**汉字（基本区 + 扩展A + 兼容 + 假名 + 标点），
              按码位切成若干片，每片带 unicode-range。
              只有真的渲染到「A、B 都没有的字」时，浏览器才会去下对应那一片。

这样：全站所有汉字都有霞鹜文楷字形（不会再出现一半套一半不套），
而首屏仍然只下 A 那一份。

产物
----
  src/assets/fonts/lxgw-wenkai-content.woff2          A
  src/assets/fonts/lxgw-wenkai-content-lyrics.woff2   B
  src/assets/fonts/lxgw-wenkai-ext-N.woff2            C 的分片
  src/styles/fonts.css                                @font-face 声明（build_site 会内联进 main.css）

缺 fonttools/brotli、或缺字体包时自动跳过，页面回落到系统字体栈，不阻塞构建。
字体包默认找 .cache/fonts/lxgw-wenkai-v1.522.zip，可用环境变量 LXGW_FONT_ARCHIVE 覆盖。
"""

import glob
import html
import json
import os
import re
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DIST = os.path.join(ROOT, "dist")
SRC = os.path.join(ROOT, "src")
SRC_FONTS = os.path.join(SRC, "assets", "fonts")
FONTS_CSS = os.path.join(SRC, "styles", "fonts.css")
CACHE = os.path.join(ROOT, ".cache", "fonts")
DEFAULT_ARCHIVE = os.path.join(CACHE, "lxgw-wenkai-v1.522.zip")

# 无论内容如何都必须保留的字符（数字、拉丁、常用标点、单位）
ALWAYS = (
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    " .,:;!?'\"()[]{}<>/\\|-_+=*&^%$#@~`"
    "，。、；：！？…—－·「」『』《》〈〉（）【】〔〕“”‘’"
    "·×÷±≈≤≥→←↑↓№℃°"
    "年月日时分秒周星期"
)

# 覆盖：CJK标点、平假名、片假名、注音/扩展、汉字、兼容表单、兼容标点、全角符号
CJK = re.compile(
    r"[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff"
    r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]"
)

LOCALES = ("zh-CN", "zh-TW", "en", "ja")

# C 层覆盖的码位区块：汉字为主体，另把拉丁/希腊/西里尔/常用符号/假名/标点也纳入，
# 保证「A、B 里没有的字」都能在 C 里找到，不会有漏网的字符。
C_BLOCKS = (
    (0x0020, 0x007E), (0x00A0, 0x024F), (0x0370, 0x03FF), (0x0400, 0x04FF),
    (0x2000, 0x206F), (0x2070, 0x209F), (0x20A0, 0x20CF), (0x2100, 0x214F),
    (0x2150, 0x218F), (0x2190, 0x21FF), (0x2200, 0x22FF), (0x2460, 0x24FF),
    (0x25A0, 0x25FF), (0x2600, 0x26FF), (0x2700, 0x27BF),
    (0x3000, 0x303F), (0x3040, 0x309F), (0x30A0, 0x30FF), (0x31F0, 0x31FF),
    (0x3200, 0x32FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF), (0xFE10, 0xFE4F), (0xFF00, 0xFFEF),
)

CHUNK_TARGET_BYTES = 560 * 1024      # C 每片的目标体积
BYTES_PER_CHAR = 230                 # 实测的经验值，仅用于估算分片


def _visible_chars(text):
    """上屏可能出现的字符：CJK 区段 + 所有非 ASCII。

    只取 CJK 区段是不够的 —— 界面里还有 ⠿（拖拽把手）、★ ☆（评分）、
    ▶ ⭘（BGM 按钮）、∠ ω ⌒（简介里的符号）这类非汉字符号。它们一样会渲染，
    漏掉就会让浏览器顺着字体栈往下回退，白白多下载「歌词层 + 汉字分片」两份字体。
    """
    out = set(CJK.findall(text))
    out |= {c for c in text if ord(c) > 0x7F}
    return out


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def collect_page_chars():
    """首屏（所有页面）会出现的字。"""
    chars = set(ALWAYS)
    files = []
    for pat in ("**/*.html", "**/*.css", "**/*.js"):
        files += glob.glob(os.path.join(DIST, pat), recursive=True)
    for code in LOCALES:
        files.append(os.path.join(SRC, "i18n", code + ".json"))
    files.append(os.path.join(ROOT, "config", "site.json"))
    n = 0
    for p in files:
        t = _read(p)
        if not t:
            continue
        chars |= _visible_chars(t)
        # 模板里有写成实体的字符（&#9654; = ▶、&#9211; = ⏻ …），
        # 只看原始文本会当成 ASCII 漏掉，浏览器那边却会解码成真字符去要字形。
        chars |= _visible_chars(html.unescape(t))
        n += 1
    return chars, n


def collect_bgm_chars():
    """BGM 面板上的曲名 —— 面板在首屏就渲染，所以这些字必须留在 A 里，
    否则一进页面就会去下 B。"""
    p = os.path.join(DIST, "assets", "bgm-meta.json")
    if not os.path.exists(p):
        return set(), 0
    try:
        data = json.loads(_read(p) or "{}")
    except ValueError:
        return set(), 0
    chars = set()
    n = 0
    for v in (data or {}).values():
        if not isinstance(v, dict):
            continue
        for key in ("t", "a"):
            if v.get(key):
                chars |= _visible_chars(v[key])
                n += 1
    return chars, n


def collect_lyric_chars():
    """歌词用字（含翻译歌词）—— 只在播放器打开时才上屏。"""
    p = os.path.join(DIST, "assets", "player-data.json")
    if not os.path.exists(p):
        return set(), 0
    try:
        data = json.loads(_read(p) or "{}")
    except ValueError:
        return set(), 0
    chars = set()
    n = 0
    for k, v in (data or {}).items():
        if k == "__build" or not isinstance(v, dict):
            continue
        for key in ("l", "t"):
            if v.get(key):
                chars |= _visible_chars(v[key])
                n += 1
    return chars, n


def collect_search_chars():
    """站内检索索引：只有真的去搜索才上屏。"""
    chars = set()
    files = sorted(glob.glob(os.path.join(DIST, "assets", "search-index.*.json")))
    for p in files:
        chars |= _visible_chars(_read(p))
    return chars, len(files)


# ---------------------------------------------------------------- 字体包

def resolve_archive(cfg):
    env = os.environ.get("LXGW_FONT_ARCHIVE")
    if env:
        return env if os.path.isabs(env) else os.path.join(ROOT, env)
    raw = ((cfg.get("fonts") or {}).get("archive") or "").strip()
    if raw:
        p = raw if os.path.isabs(raw) else os.path.join(ROOT, raw)
        if os.path.exists(p):
            return p
    return DEFAULT_ARCHIVE


def find_ttf(cfg):
    fonts_cfg = cfg.get("fonts") or {}
    zpath = resolve_archive(cfg)
    want = fonts_cfg.get("preferred") or "lxgw-wenkai-v1.522/LXGWWenKai-Regular.ttf"
    fallback = fonts_cfg.get("fallback") or "lxgw-wenkai-v1.522/LXGWWenKai-Light.ttf"
    if not os.path.exists(zpath):
        return None, "字体包不存在：%s" % zpath
    os.makedirs(CACHE, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".ttf")]
        pick = None
        for cand in (want, fallback):
            if cand in names:
                pick = cand
                break
        if pick is None:
            picks = [n for n in names if "Mono" not in n]
            pick = (picks or names)[0]
        out = os.path.join(CACHE, os.path.basename(pick))
        if not os.path.exists(out) or os.path.getsize(out) < 100000:
            t0 = time.time()
            with z.open(pick) as src, open(out, "wb") as dst:
                while True:
                    buf = src.read(1 << 20)
                    if not buf:
                        break
                    dst.write(buf)
            print("  从压缩包取出字体：%s（%.1fs）" % (os.path.basename(pick), time.time() - t0))
        return out, None


# ---------------------------------------------------------------- 子集化

def make_subset(subset_mod, ttf, chars, target, extra_ranges=()):
    """把 chars（外加 extra_ranges 覆盖的码位）切进 target。"""
    # 注意：这里**不能**用 c.strip() 过滤 —— 空格 U+0020 strip 之后是空串，
    # 被滤掉的话字体里就没有空格字形，浏览器会为每个空格往下一层回退，
    # 白白多下一份 ext 分片（踩过）。
    cps = {ord(c) for c in chars}
    for lo, hi in extra_ranges:
        cps |= set(range(lo, hi + 1))
    text = "".join(chr(c) for c in sorted(cps))

    options = subset_mod.Options()
    options.flavor = "woff2"
    options.desubroutinize = True
    options.drop_tables += ["DSIG"]
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.recalc_bounds = True
    options.recalc_timestamp = False
    options.hinting = not options.desubroutinize

    font = subset_mod.load_font(ttf, options)
    missing = []
    try:
        cmap = set(font.getBestCmap().keys())
        missing = sorted({c for c in chars if c.strip() and ord(c) not in cmap})
        subsetter = subset_mod.Subsetter(options=options)
        subsetter.populate(text=text)
        subsetter.subset(font)
        subset_mod.save_font(font, target, options)
    finally:
        font.close()
    return missing


def chunk_codepoints(cps, target_bytes=CHUNK_TARGET_BYTES):
    """按码位顺序把 cps 切成若干片，每片体积大致不超过 target。"""
    cps = sorted(cps)
    chunks, cur = [], []
    for c in cps:
        cur.append(c)
        if len(cur) * BYTES_PER_CHAR >= target_bytes:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def contiguous_ranges(cps):
    """把码位集合压成连续区间。"""
    out = []
    cps = sorted(cps)
    i = 0
    while i < len(cps):
        j = i
        while j + 1 < len(cps) and cps[j + 1] == cps[j] + 1:
            j += 1
        out.append((cps[i], cps[j]))
        i = j + 1
    return out


# ---------------------------------------------------------------- CSS

FONT_FACE = """@font-face {
  font-family: "%(family)s";
  src: url("../fonts/%(file)s") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: swap;
%(range)s}"""


def css_ranges(codepoints):
    """把码位集合写成 CSS unicode-range 列表。"""
    toks = []
    for lo, hi in contiguous_ranges(codepoints):
        toks.append("U+%04X" % lo if lo == hi else "U+%04X-%04X" % (lo, hi))
    return ",".join(toks)


def write_fonts_css(a_file, b_file, b_cps, c_chunks):
    parts = ["/* 由 scripts/build_font.py 自动生成，请勿手改。",
             "   分三层：Content（首屏用字，必下）→ Lyrics（歌词/检索用字，按需）",
             "   → Ext（霞鹜文楷其余全部汉字，按 unicode-range 分片按需）。 */", ""]
    parts.append(FONT_FACE % {"family": "LXGW WenKai Content", "file": a_file, "range": ""})
    parts.append("")
    if b_file:
        # 带 unicode-range：字符不在范围内时浏览器直接跳过这一层，不会先下载再判断
        parts.append(FONT_FACE % {
            "family": "LXGW WenKai Lyrics", "file": b_file,
            "range": '  unicode-range: %s;\n' % css_ranges(b_cps),
        })
        parts.append("")
    for fname, cps in c_chunks:
        parts.append(FONT_FACE % {
            "family": "LXGW WenKai Ext",
            "file": fname,
            "range": '  unicode-range: %s;\n' % css_ranges(cps),
        })
        parts.append("")
    css = "\n".join(parts).rstrip() + "\n"
    with open(FONTS_CSS, "w", encoding="utf-8") as f:
        f.write(css)
    return len(css)


# ---------------------------------------------------------------- main

def main():
    cfg = json.loads(_read(os.path.join(ROOT, "config", "site.json")) or "{}")
    name = (cfg.get("fonts") or {}).get("outputName") or "lxgw-wenkai-content"
    os.makedirs(SRC_FONTS, exist_ok=True)

    try:
        from fontTools import subset as subset_mod
    except ImportError:
        print("  ! 未安装 fonttools，跳过字体子集化（页面使用系统字体栈回退）")
        return 0

    ttf, err = find_ttf(cfg)
    if not ttf:
        print("  ! %s" % err)
        print("  - 保留仓库里已有的字体与 fonts.css（全量汉字仍然可用），跳过重新生成")
        return 0
    orig = os.path.getsize(ttf)

    # ---------- 分层取字 ----------
    page, n_page = collect_page_chars()
    bgm, n_bgm = collect_bgm_chars()
    lyric, n_lyric = collect_lyric_chars()
    search, n_search = collect_search_chars()

    a_chars = page | bgm | set(ALWAYS)
    b_chars = (lyric | search) - a_chars
    use_lyric_font = bool((cfg.get("player") or {}).get("lyricFont", True))

    # ---------- C 层：全量汉字 ----------
    from fontTools.ttLib import TTFont
    probe = TTFont(ttf, lazy=True)
    font_cps = set(probe.getBestCmap().keys())
    probe.close()

    c_all = set()
    for lo, hi in C_BLOCKS:
        c_all |= {c for c in range(lo, hi + 1) if c in font_cps}
    a_b_cps = {ord(c) for c in a_chars} | {ord(c) for c in b_chars}
    # 分片按 c_all 连续切：声明范围只有几段，CSS 很小。
    # （A/B 用字由前面两层负责，不必从 ext 的声明范围里挖掉。）
    chunks = chunk_codepoints(c_all)
    print("  C 层：霞鹜文楷在该范围内共 %d 个码位，切成 %d 片" % (len(c_all), len(chunks)))

    # ---------- 清掉上一轮的 ext 分片，避免残留 ----------
    for old in glob.glob(os.path.join(SRC_FONTS, "lxgw-wenkai-ext-*.woff2")):
        os.remove(old)

    # ---------- A ----------
    a_file = name + ".woff2"
    t0 = time.time()
    missing = make_subset(subset_mod, ttf, a_chars, os.path.join(SRC_FONTS, a_file))
    a_size = os.path.getsize(os.path.join(SRC_FONTS, a_file))
    print("  %-8s %2d 个来源，%5d 字 -> %.0f KB（原字体 %.1f%%），%.1fs"
          % ("content", n_page + n_bgm, len(a_chars), a_size / 1024,
             a_size * 100.0 / orig, time.time() - t0))
    if missing:
        print("           字体缺失 %d 字（回落系统字体）：%s" % (len(missing), "".join(missing[:30])))

    # ---------- B ----------
    b_file = None
    if use_lyric_font and b_chars:
        b_file = name + "-lyrics.woff2"
        t0 = time.time()
        miss_b = make_subset(subset_mod, ttf, b_chars, os.path.join(SRC_FONTS, b_file))
        b_size = os.path.getsize(os.path.join(SRC_FONTS, b_file))
        print("  %-8s %2d 个来源，%5d 字 -> %.0f KB（原字体 %.1f%%），%.1fs"
              % ("lyrics", n_lyric + n_search, len(b_chars), b_size / 1024,
                 b_size * 100.0 / orig, time.time() - t0))
        if miss_b:
            print("           字体缺失 %d 字：%s" % (len(miss_b), "".join(miss_b[:30])))
    else:
        print("  - 配置关掉了歌词字体（player.lyricFont=false）或没有歌词来源，跳过 B 层")

    # ---------- C ----------
    c_files = []
    t0 = time.time()
    c_total = 0
    for i, cp_chunk in enumerate(chunks, 1):
        fname = "lxgw-wenkai-ext-%d.woff2" % i
        target = os.path.join(SRC_FONTS, fname)
        # 字体内容去掉 A/B 用字（省重复字形）；声明范围用整片（连续，CSS 短）
        body = [c for c in cp_chunk if c not in a_b_cps]
        make_subset(subset_mod, ttf, set(), target, extra_ranges=contiguous_ranges(body))
        c_total += os.path.getsize(target)
        c_files.append((fname, cp_chunk))
    print("  %-8s %d 片，%d 个码位 -> 合计 %.1f MB，%.1fs"
          % ("ext", len(c_files), len(c_all), c_total / 1048576.0, time.time() - t0))

    # 只声明「字体里真的有的字」：字体没有的符号（❃ ❚ ⠿ …）不该被这一层认领，
    # 否则浏览器会为了它们把整份歌词字体下下来，再发现没有字形、继续往下回退。
    b_cps = ({ord(c) for c in b_chars} & font_cps) if b_file else set()
    css_len = write_fonts_css(a_file, b_file, b_cps, c_files)
    print("  生成 %s（%.1f KB）" % (os.path.relpath(FONTS_CSS, ROOT), css_len / 1024))
    print("  首屏只需 content 一份：%.0f KB" % (a_size / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
