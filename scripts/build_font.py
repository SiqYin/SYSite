"""字体子集化：把 25MB 的霞鹜文楷切成只含站点实际用字的 woff2。

设计要点：
- 扫描「构建产物」（dist 下的 html/css/js）来收集字符，而不是只看数据文件 ——
  这样 JS 运行时拼出来的字符串（日期、标签、提示语）也一并覆盖，
  未来新增投稿带来的新字会在下次构建时自动进入子集，无需人工维护。
- 缺 fonttools/brotli 时自动跳过，页面回落到系统字体栈，不阻塞构建。
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

CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]")


def collect_chars():
    """只取「真正会被渲染」的文本：构建产物 + 界面文案 + 配置。

    刻意不含 data/snapshot.json —— 它只是一份随站点发布的数据副本，
    其中的字段未必全部上屏；把它算进来会让字体凭空胖一圈。
    每次构建都会重跑本脚本，所以新增投稿的用字会自动补进子集。
    """
    chars = set(ALWAYS)
    files = []
    for pat in ("**/*.html", "**/*.css", "**/*.js"):
        files += glob.glob(os.path.join(DIST, pat), recursive=True)
    # 刻意不含 assets/search-index.*.json：
    # 搜索结果展示的标题/专辑名在内容页上都出现过，而索引里还带着只用于检索、
    # 从不上屏的描述文本，算进来会让字体凭空胖一倍。
    for code in ("zh-CN", "zh-TW", "en", "ja"):
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


def main():
    cfg = json.load(open(os.path.join(ROOT, "config", "site.json"), "r", encoding="utf-8"))
    out_name = cfg["fonts"]["outputName"]
    os.makedirs(SRC_FONTS, exist_ok=True)
    target = os.path.join(SRC_FONTS, out_name + ".woff2")

    try:
        from fontTools import subset
    except ImportError:
        print("  ! 未安装 fonttools，跳过字体子集化（页面使用系统字体栈回退）")
        return 0

    ttf, err = find_ttf(cfg)
    if not ttf:
        print("  ! %s，跳过字体子集化" % err)
        return 0

    chars, nfiles = collect_chars()
    print("  扫描 %d 个构建产物文件，共需 %d 个字符" % (nfiles, len(chars)))

    text = "".join(sorted(chars))
    t0 = time.time()
    options = subset.Options()
    options.flavor = "woff2"
    options.desubroutinize = True
    options.drop_tables += ["DSIG"]
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.recalc_bounds = True
    options.recalc_timestamp = False
    options.hinting = not options.desubroutinize

    font = subset.load_font(ttf, options)
    try:
        cmap = set(font.getBestCmap().keys())
        missing = sorted({c for c in chars if ord(c) not in cmap and c.strip()})
        if missing:
            print("  ! 字体缺失 %d 个字符（将回落系统字体）：%s"
                  % (len(missing), "".join(missing[:40])))
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(text=text)
        subsetter.subset(font)
        subset.save_font(font, target, options)
    finally:
        font.close()

    orig = os.path.getsize(ttf)
    new = os.path.getsize(target)
    print("  霞鹜文楷子集：%.1f MB -> %.0f KB（%.1f%%），用时 %.1fs"
          % (orig / 1048576, new / 1024, new * 100.0 / orig, time.time() - t0))
    print("  产出：%s" % os.path.relpath(target, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
