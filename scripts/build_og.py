"""分享卡片（Open Graph 图）生成。

为每个语言 × 每个页面生成一张 1200×630 的卡片，分享到微信/QQ/Twitter 时能出预览图。
用霞鹜文楷渲染，配色与站点一致；缺 Pillow 或字体时自动跳过，不阻塞构建。
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import build_font  # noqa: E402  复用字体解压逻辑，避免两处各写一份

CONFIG = os.path.join(ROOT, "config", "site.json")
SNAPSHOT = os.path.join(ROOT, "data", "snapshot.json")
OUTDIR = os.path.join(ROOT, "src", "assets", "og")

W, H = 1200, 630
BG = (244, 249, 253)
INK = (26, 42, 58)
DEEP = (15, 47, 71)
BLUE = (41, 128, 185)
BLUE_D = (26, 82, 118)
BLUE_L = (200, 218, 232)
TEAL = (63, 182, 168)

# (页面 key, 标题键, 副标题键)
PAGES = [
    ("index", "site.name", "site.desc"),
    ("videos", "nav.videos", "section.videos.sub"),
    ("music", "nav.music", "section.music.sub"),
    ("articles", "nav.articles", "section.articles.sub"),
    ("projects", "nav.projects", "section.projects.sub"),
    ("about", "about.title", "site.tagline"),
    ("stats", "stats.title", "stats.sub"),
]

LOCALES = [("zh-CN", ""), ("zh-TW", "zh-TW"), ("en", "en"), ("ja", "ja")]


def load(p, d=None):
    if not os.path.exists(p):
        return d
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def fit(draw, text, font_path, size, max_w, min_size=22):
    """自动缩字号直到放下（中文长标题很常见）。"""
    from PIL import ImageFont
    while size > min_size:
        f = ImageFont.truetype(font_path, size)
        box = draw.textbbox((0, 0), text, font=f)
        if box[2] - box[0] <= max_w:
            return f
        size -= 2
    return ImageFont.truetype(font_path, min_size)


def wrap(draw, text, font, max_w, max_lines=2):
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and len("".join(lines)) < len(text):
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > max_w:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def circle_bg(draw, cx, cy, r, color):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)


def main():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  ! 未安装 Pillow，跳过分享卡片生成")
        return 0

    cfg = load(CONFIG)
    snap = load(SNAPSHOT, {}) or {}
    owner = cfg["site"]["owner"]

    font_ttf, err = build_font.find_ttf(cfg)
    if not font_ttf:
        print("  ! %s，跳过分享卡片生成" % err)
        return 0
    FONT_TTF = font_ttf

    os.makedirs(OUTDIR, exist_ok=True)
    t0 = time.time()
    count = 0
    for code, _ in LOCALES:
        zh = load(os.path.join(ROOT, "src", "i18n", "zh-CN.json"), {}) or {}
        loc = load(os.path.join(ROOT, "src", "i18n", code + ".json"), {}) or {}
        s = dict(zh)
        s.update({k: v for k, v in loc.items() if not k.startswith("_")})

        for page, tk, sk in PAGES:
            title = s.get(tk) or cfg["site"]["id"]
            sub = s.get(sk) or ""
            im = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(im)

            # 背景装饰
            circle_bg(d, W - 90, 80, 190, (232, 242, 250))
            circle_bg(d, W - 200, 210, 110, (223, 238, 249))
            d.rectangle((0, 0, 10, H), fill=BLUE)

            # 站点名
            f_name = fit(d, title, FONT_TTF, 82, W - 200)
            d.text((88, 132), title, font=f_name, fill=DEEP)

            # 分隔线
            d.rounded_rectangle((90, 246, 190, 252), radius=3, fill=BLUE)

            # 页面名
            f_page = fit(d, sub, FONT_TTF, 36, W - 220)
            for i, line in enumerate(wrap(d, sub, f_page, W - 220, 2)):
                d.text((90, 288 + i * 50), line, font=f_page, fill=(91, 127, 158))

            # 底部：作者 + 站点
            d.text((90, H - 118), owner, font=__import__("PIL.ImageFont", fromlist=["truetype"]).truetype(FONT_TTF, 34), fill=BLUE_D)
            f_bottom = __import__("PIL.ImageFont", fromlist=["truetype"]).truetype(FONT_TTF, 26)
            site_label = "%s · %s" % (cfg["site"]["url"].replace("https://", ""), code)
            d.text((90, H - 70), site_label, font=f_bottom, fill=(122, 153, 181))

            # 萤火点缀
            circle_bg(d, W - 148, H - 96, 7, TEAL)
            circle_bg(d, W - 122, H - 126, 4, BLUE)

            out = os.path.join(OUTDIR, "%s-%s.jpg" % (code, page))
            im.save(out, "JPEG", quality=88, optimize=True)
            count += 1

    total = sum(os.path.getsize(os.path.join(OUTDIR, f)) for f in os.listdir(OUTDIR))
    print("  生成 %d 张分享卡片，共 %.1f MB（平均 %.0f KB），用时 %.1fs"
          % (count, total / 1048576, total / max(count, 1) / 1024, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
