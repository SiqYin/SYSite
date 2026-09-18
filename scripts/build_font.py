"""字体子集化：把 25MB 的霞鹜文楷切成只含站点实际用字的 woff2。

拆成两份：
1. 主字体（content）：扫描 dist 下的 html/css/js + 四语文案，界面与内容页用，始终加载；
2. 歌词字体（lyrics）：扫描 assets/player-data.json 里的歌词文本，
   只在播放器打开时由 .op-lyrics 用到，单独一个文件按需下载。

为什么要拆：歌词里古今字、方言字、生僻字特别多，和主字体混在一起会让首屏字体
平白胖好几倍；拆开后首屏体积不变，歌词也不会缺字。

缺 fonttools/brotli 时自动跳过，页面回落到系统字体栈，不阻塞构建。
"""

import glob
import json
import os
import re
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DIST = os.path.join(ROOT, "dist")
SRC_FONTS = os.path.join(ROOT, "src", "assets", "fonts")
CACHE = os.path.join(ROOT, ".cache", "fonts")

# 无论内容如何都必须保留的字符（数字、拉丁、常用标点、单位）
ALWAYS = (
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    " .,:;!?'\"()[]{}<>/\\|-_+=*&^%$#@~`"
    "，。、；：！？…—－·「」『』《》〈〉（）【】〔〕“”‘’"
    "·×÷±≈≤≥→←↑↓№℃°"
    "年月日时分秒周星期"
)

# 覆盖：CJK标点、平假名、片假名、注音/扩展、汉字、兼容表单、兼容标点、全角符号
# （漏掉假名区段会导致日文页面的假名全部回落系统字体——踩过一次）
CJK = re.compile(
    r"[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff"
    r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]"
)

LOCALES = ("zh-CN", "zh-TW", "en", "ja")


def collect_page_chars():
    """界面与内容页用字。

    刻意不含 assets/search-index.*.json：搜索结果展示的标题在内容页上都出现过，
    而索引里带着只用于检索、从不上屏的描述文本，算进来会让字体凭空胖一圈。
    """
    chars = set(ALWAYS)
    files = []
    for pat in ("**/*.html", "**/*.css", "**/*.js"):
        files += glob.glob(os.path.join(DIST, pat), recursive=True)
    for code in LOCALES:
        files.append(os.path.join(ROOT, "src", "i18n", code + ".json"))
    files.append(os.path.join(ROOT, "config", "site.json"))

    n = 0
    for p in files:
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()
        except OSError:
            continue
        chars |= set(CJK.findall(txt))
        chars |= set(re.findall(r"[\u2000-\u206f]", txt))
        n += 1
    return chars, n


def collect_lyric_chars():
    """播放器里的歌词用字（含翻译歌词）。"""
    p = os.path.join(DIST, "assets", "player-data.json")
    if not os.path.exists(p):
        return set(), 0
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return set(), 0
    chars = set(ALWAYS)
    n = 0
    for v in (data or {}).values():
        for key in ("l", "t"):
            txt = v.get(key)
            if txt:
                chars |= set(CJK.findall(txt))
                chars |= set(re.findall(r"[\u2000-\u206f\u3040-\u30ff]", txt))
                n += 1
    return chars, n


def find_ttf(cfg):
    zpath = cfg["fonts"]["archive"]
    want = cfg["fonts"]["preferred"]
    fallback = cfg["fonts"]["fallback"]
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


def make_subset(subset_mod, ttf, chars, target):
    text = "".join(sorted(chars))
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
        missing = sorted({c for c in chars if ord(c) not in cmap and c.strip()})
        subsetter = subset_mod.Subsetter(options=options)
        subsetter.populate(text=text)
        subsetter.subset(font)
        subset_mod.save_font(font, target, options)
    finally:
        font.close()
    return missing


def main():
    cfg = json.load(open(os.path.join(ROOT, "config", "site.json"), "r", encoding="utf-8"))
    name = cfg["fonts"]["outputName"]
    os.makedirs(SRC_FONTS, exist_ok=True)

    try:
        from fontTools import subset as subset_mod
    except ImportError:
        print("  ! 未安装 fonttools，跳过字体子集化（页面使用系统字体栈回退）")
        return 0

    ttf, err = find_ttf(cfg)
    if not ttf:
        print("  ! %s，跳过字体子集化" % err)
        return 0
    orig = os.path.getsize(ttf)

    jobs = [("content", collect_page_chars(), name + ".woff2"),
            ("lyrics", collect_lyric_chars(), name + "-lyrics.woff2")]
    if not ((cfg.get("player") or {}).get("lyricFont", True)):
        jobs = jobs[:1]
        print("  - 配置里关掉了歌词字体（player.lyricFont=false），跳过第二份子集")
    for label, (chars, nsrc), fname in jobs:
        if not chars or len(chars) <= len(ALWAYS):
            print("  - %s：没有可用的取字来源，跳过" % label)
            continue
        target = os.path.join(SRC_FONTS, fname)
        t0 = time.time()
        missing = make_subset(subset_mod, ttf, chars, target)
        new = os.path.getsize(target)
        print("  %-8s 扫描 %2d 个来源，%5d 字 -> %.0f KB（原字体的 %.1f%%），用时 %.1fs"
              % (label, nsrc, len(chars), new / 1024, new * 100.0 / orig, time.time() - t0))
        if missing:
            print("           字体缺失 %d 个字符（回落系统字体）：%s"
                  % (len(missing), "".join(missing[:30])))
    print("  产出目录：%s" % os.path.relpath(SRC_FONTS, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
