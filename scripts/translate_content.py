#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""翻译记忆 + 增量翻译。

做什么：
  把「内容」翻译成站点的其它语言——稿件标题（文集/项目/音乐/视频）、文集名、歌词正文。
  译文全部落在 data/i18n-cache.json，构建期只读这份缓存，不再调接口。

翻译记忆（translation memory）：
  缓存按「原文」比对。同一条内容只要原文没变，就永远复用第一次翻的译文——
  英语/日语读者无论打开多少次，看到的同一个项目名字都是一样的。
  原文被改了（比如 B 站改了视频标题），那一条才会重新翻译，其余不受影响。

用法：
  SF_API_KEY=xxx python scripts/translate_content.py              # 标题 + 文集 + 歌词
  SF_API_KEY=xxx python scripts/translate_content.py --only titles
  SF_API_KEY=xxx python scripts/translate_content.py --limit 20    # 试跑
"""
import json
import os
import re
import sys
import time
import hashlib
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, "data", "snapshot.json")
CACHE = os.path.join(ROOT, "data", "i18n-cache.json")
LOCALES = ["en", "zh-TW", "ja"]
LANG_NAME = {"en": "英语 (English)", "zh-TW": "繁体中文（台灣用語）", "ja": "日语（自然、书面）"}
API = os.environ.get("SF_API_URL", "https://api.siliconflow.cn/v1/chat/completions")
MODEL = os.environ.get("SF_MODEL", "Qwen/Qwen3.5-9B")
KEY = os.environ.get("SF_API_KEY", "").strip()
THROTTLE = float(os.environ.get("SF_THROTTLE", "1.2"))
BATCH = 20

GLOSSARY = {
    "洛天依": {"en": "Luo Tianyi", "ja": "洛天依", "zh-TW": "洛天依"},
    "吴语": {"en": "Shanghainese", "ja": "呉語", "zh-TW": "吳語"},
    "吴越春秋": {"en": "Wu-Yue Annals", "ja": "呉越春秋", "zh-TW": "吳越春秋"},
    "翻唱": {"en": "cover", "ja": "カバー", "zh-TW": "翻唱"},
    "原创": {"en": "original", "ja": "オリジナル", "zh-TW": "原創"},
    "言和": {"en": "Yanhe", "ja": "言和", "zh-TW": "言和"},
    "乐正绫": {"en": "Yuezheng Ling", "ja": "楽正綾", "zh-TW": "樂正綾"},
}

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LRC = re.compile(r"^(?:\[\d+:\d+(?:[.:]\d+)?\])+(.*)$")


def log(*a):
    print(*a, flush=True)


def load_json(p, default):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, p)


def api(messages, max_tokens=1500, temperature=0.2, retries=3):
    if not KEY:
        raise SystemExit("缺少 SF_API_KEY")
    body = json.dumps({
        "model": MODEL, "messages": messages,
        "max_tokens": max_tokens, "temperature": temperature,
        "enable_thinking": False,
    }).encode()
    last = None
    for i in range(retries):
        try:
            r = urllib.request.Request(API, data=body, headers={
                "Authorization": "Bearer " + KEY,
                "Content-Type": "application/json",
                "User-Agent": "SYSite-translate",
            })
            with urllib.request.urlopen(r, timeout=120) as resp:
                d = json.loads(resp.read().decode())
            time.sleep(THROTTLE)
            return d["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            last = "HTTP %d %s" % (e.code, e.read(200).decode("utf-8", "replace")[:150])
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 * (i + 1))
                continue
            raise
        except Exception as e:
            last = str(e)[:120]
            time.sleep(2 * (i + 1))
    raise RuntimeError("接口连续失败：%s" % last)


def translate_lines(items, locale, retries=2):
    """items: 待翻字符串列表 → 与输入等长、等序的译文列表。"""
    out = []
    for i in range(0, len(items), BATCH):
        chunk = items[i:i + BATCH]
        got = _translate_chunk(chunk, locale)
        if got is None or len(got) != len(chunk):
            got = []
            for one in chunk:                      # 整批失败就逐条来
                r = _translate_chunk([one], locale)
                got.append(r[0] if r and len(r) == 1 else one)
        out.extend(got)
    return out


def _clean(s):
    """去掉换行/多余空白，避免一条输入被模型拆成多行。"""
    return re.sub(r"\s+", " ", (s or "")).strip()


def _translate_chunk(chunk, locale):
    chunk = [_clean(s) for s in chunk]
    numbered = "\n".join("%d. %s" % (n + 1, s) for n, s in enumerate(chunk))
    rules = "；".join("%s → %s" % (k, v[locale]) for k, v in GLOSSARY.items())
    sys_p = ("你是专业译者，负责把中文作品名/歌词译成%s。"
             "要求：译文自然、保留原有语气与专有名词，不添加解释，不要意译成无关内容。"
             "以下术语必须严格按给定译法，保持全站统一：%s。"
             "注意：英文里 Shanghainese 指整个吴语，不是只指上海话。" % (LANG_NAME[locale], rules))
    user = ("把下面每一条翻译成%s。"
            "严格只输出译文，一条一行，条数和顺序必须与输入完全一致，不要编号、不要空行、不要任何说明。\n\n%s"
            % (LANG_NAME[locale], numbered))
    for _ in range(2):
        try:
            txt = api([{"role": "system", "content": sys_p},
                       {"role": "user", "content": user}],
                      max_tokens=min(3000, 80 * len(chunk) + 200))
        except Exception as e:
            log("      ! 调用失败:", str(e)[:90])
            return None
        # 按序号认领：模型给的编号最可靠，缺号/多号都能看出来
        got = {}
        for line in txt.strip().split("\n"):
            m = re.match(r"^\s*(\d+)\s*[.、)]\s*(.+)$", line.strip())
            if m:
                idx = int(m.group(1))
                if 1 <= idx <= len(chunk) and idx not in got:
                    got[idx] = m.group(2).strip()
        if len(got) == len(chunk):
            return [got[i + 1] for i in range(len(chunk))]
        # 少数几条没认领到 → 只补这几条
        missing = [i for i in range(len(chunk)) if (i + 1) not in got]
        for i in missing:
            r = _translate_one(chunk[i], locale)
            if r:
                got[i + 1] = r
        if len(got) == len(chunk):
            return [got[i + 1] for i in range(len(chunk))]
    return None


def _translate_one(text, locale):
    for _ in range(2):
        try:
            txt = api([{"role": "user",
                        "content": "把下面这条中文翻译成%s，只输出译文本身，不要任何解释或编号：\n%s"
                                   % (LANG_NAME[locale], text)}], max_tokens=600)
        except Exception:
            return None
        out = re.sub(r"^\s*\d+[.、)]\s*", "", txt.strip().split("\n")[0]).strip()
        if out:
            return out
    return None


def parse_lyric_lines(l):
    """从 LRC 里取出「正文行」文本（保留原顺序，去重后返回唯一文本列表）。"""
    texts, seen = [], set()
    for raw in (l or "").split("\n"):
        raw = raw.strip()
        if not raw:
            continue
        m = LRC.match(raw)
        t = (m.group(1) if m else raw).strip()
        if not t or t in seen:
            continue
        seen.add(t)
        texts.append(t)
    return texts


def main():
    only = "all"
    limit = 0
    deadline = time.time() + float(os.environ.get("SF_BUDGET", "3000"))
    for a in sys.argv[1:]:
        if a.startswith("--only="):
            only = a.split("=", 1)[1]
        elif a == "--only" and sys.argv.index(a) + 1 < len(sys.argv):
            only = sys.argv[sys.argv.index(a) + 1]
        elif a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])

    snap = load_json(SNAP, {})
    items = snap.get("items") or []
    cols = snap.get("collections") or []
    player = snap.get("player") or {}
    cache = load_json(CACHE, {"schema": 1, "titles": {}, "collections": {}, "lyrics": {}})
    for k in ("titles", "collections", "lyrics"):
        cache.setdefault(k, {})
    cache["model"] = MODEL
    cache["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    stats = {"titles": 0, "collections": 0, "lyrics": 0, "reused": 0, "skipped": 0}

    # ---------- 1) 稿件标题 ----------
    if only in ("all", "titles"):
        todo = []
        for it in items:
            iid, title = it.get("id"), (it.get("title") or "").strip()
            if not iid or not title or not CJK.search(title):
                stats["skipped"] += 1
                continue
            ent = cache["titles"].get(iid)
            if ent and ent.get("src") == title and all(ent.get(x) for x in LOCALES):
                stats["reused"] += 1
                continue
            todo.append((iid, title))
        if limit:
            todo = todo[:limit]
        log("标题：待翻 %d 条，复用 %d 条" % (len(todo), stats["reused"]))
        if todo:
            for loc in LOCALES:
                if time.time() > deadline:
                    log("   时间预算用完，已保存，下次续跑"); break
                res = translate_lines([t for _, t in todo], loc)
                for (iid, title), tr in zip(todo, res):
                    cache["titles"].setdefault(iid, {"src": title})
                    cache["titles"][iid]["src"] = title
                    cache["titles"][iid][loc] = tr
                save_json(CACHE, cache)
                log("   %-6s 完成 %d 条" % (loc, len(todo)))
            stats["titles"] = len(todo)

    # ---------- 2) 文集名 ----------
    if only in ("all", "collections"):
        todo = []
        for c in cols:
            cid, title = c.get("id"), (c.get("title") or "").strip()
            if not cid or not title or not CJK.search(title):
                continue
            ent = cache["collections"].get(cid)
            if ent and ent.get("src") == title and all(ent.get(x) for x in LOCALES):
                stats["reused"] += 1
                continue
            todo.append((cid, title))
        log("文集：待翻 %d 条" % len(todo))
        if todo:
            for loc in LOCALES:
                if time.time() > deadline:
                    log("   时间预算用完，已保存，下次续跑"); break
                res = translate_lines([t for _, t in todo], loc)
                for (cid, title), tr in zip(todo, res):
                    cache["collections"].setdefault(cid, {"src": title})
                    cache["collections"][cid]["src"] = title
                    cache["collections"][cid][loc] = tr
                save_json(CACHE, cache)
                log("   %-6s 完成 %d 条" % (loc, len(todo)))
            stats["collections"] = len(todo)

    # ---------- 3) 歌词 ----------
    if only in ("all", "lyrics"):
        songs = []
        for sid, info in player.items():
            texts = [t for t in parse_lyric_lines(info.get("l")) if CJK.search(t)]
            if not texts:
                continue
            h = hashlib.md5(("\n".join(texts)).encode("utf-8")).hexdigest()[:16]
            ent = cache["lyrics"].get(sid)
            if ent and ent.get("srcHash") == h and all(ent.get(x) for x in LOCALES):
                stats["reused"] += 1
                continue
            songs.append((sid, texts, h))
        log("歌词：待翻 %d 首（共 %d 首有歌词）" % (len(songs), len(songs) + stats["reused"]))
        for n, (sid, texts, h) in enumerate(songs, 1):
            entry = {"srcHash": h}
            for loc in LOCALES:
                res = translate_lines(texts, loc)
                entry[loc] = dict(zip(texts, res))
            cache["lyrics"][sid] = entry
            save_json(CACHE, cache)
            log("   [%d/%d] %s → %d 行" % (n, len(songs), sid, len(texts)))
        stats["lyrics"] = len(songs)

    save_json(CACHE, cache)
    log("完成：新翻标题 %d、文集 %d、歌词 %d 首；复用 %d 条；跳过（无需翻）%d 条"
        % (stats["titles"], stats["collections"], stats["lyrics"], stats["reused"], stats["skipped"]))
    log("缓存文件：%s (%.1f KB)" % (CACHE, os.path.getsize(CACHE) / 1024))


if __name__ == "__main__":
    main()
