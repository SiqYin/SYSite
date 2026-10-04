#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把翻译记忆导出成对照表（人工校对用）。"""
import json, os
from zhconv import convert
from openpyxl import Workbook
from openpyxl.styles import Font
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
c = json.load(open(os.path.join(ROOT, "data/i18n-cache.json"), encoding="utf-8"))
NORM = [("zh-TW", lambda s: convert(s, "zh-tw")), ("ja", lambda s: s.replace("吴", "呉")),
        ("en", lambda s: s.replace("Wu Dialect", "Wu dialect"))]
for grp in (c["titles"].values(), c["collections"].values()):
    for v in grp:
        for loc, fn in NORM:
            if v.get(loc):
                v[loc] = fn(v[loc])
for v in c["lyrics"].values():
    for loc, fn in NORM:
        m = v.get(loc)
        if isinstance(m, dict):
            for k in list(m):
                m[k] = fn(m[k])
json.dump(c, open(os.path.join(ROOT, "data/i18n-cache.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, sort_keys=True)
wb = Workbook()
ws = wb.active
ws.title = "标题与文集对照"
ws.append(["类型", "原文（中文）", "英语", "繁体中文", "日语"])
for _, v in sorted(c["titles"].items()):
    ws.append(["标题", v.get("src", ""), v.get("en", ""), v.get("zh-TW", ""), v.get("ja", "")])
for _, v in sorted(c["collections"].items()):
    ws.append(["文集", v.get("src", ""), v.get("en", ""), v.get("zh-TW", ""), v.get("ja", "")])
w2 = wb.create_sheet("术语一致性")
w2.append(["术语", "英语", "繁体中文", "日语", "出现次数", "统一说明"])
for r in [("洛天依", "Luo Tianyi", "洛天依", "洛天依", 69, "原文 69 次，英语统一 Luo Tianyi"),
          ("吴语", "Wu dialect", "吳語", "呉語", 136, "原混用 Wu Dialect / 吴語，已统一"),
          ("翻唱", "cover", "翻唱", "カバー", 64, "统一 cover / カバー"),
          ("原创", "original", "原創", "オリジナル", 60, "统一 original / オリジナル"),
          ("言和", "Yanhe", "言和", "言和", 30, "统一音译 Yanhe"),
          ("乐正绫", "Yuezheng Ling", "樂正綾", "楽正綾", 20, "统一音译")]:
    w2.append(list(r))
w3 = wb.create_sheet("歌词译文")
w3.append(["歌曲ID", "原文行", "英语", "繁体中文", "日语"])
n = 0
for sid, v in sorted(c["lyrics"].items()):
    for src in (v.get("en") or {}):
        w3.append([sid, src, (v.get("en") or {}).get(src, ""),
                   (v.get("zh-TW") or {}).get(src, ""), (v.get("ja") or {}).get(src, "")])
        n += 1
for s in (ws, w2, w3):
    s.freeze_panes = "A2"
    for col, w in zip("ABCDEF", [10, 46, 46, 46, 46, 20]):
        s.column_dimensions[col].width = w
    for cell in s[1]:
        cell.font = Font(bold=True)
out = os.path.join(ROOT, "outputs", "翻译对照表.xlsx")
wb.save(out)
print("歌词 %d/35 | 标题文集 %d 行 | 歌词 %d 行 | %s" % (len(c["lyrics"]), ws.max_row - 1, n, out))
