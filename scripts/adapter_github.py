"""GitHub 适配器。

数据源：
- REST API 取全部仓库（描述、语言、Star、更新时间）
- 个人主页 HTML 里的 pinned 区块取精选项目及其顺序（GraphQL 需要 Token，HTML 免鉴权且稳定）
"""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_model as M  # noqa: E402

PINNED_START = "js-pinned-items-reorder-container"
PINNED_SCAN = 40000


def parse_pinned(html, username):
    """从主页 HTML 的 pinned 区块中，按卡片顺序提取精选仓库全名。"""
    idx = html.find(PINNED_START)
    if idx < 0:
        return []
    seg = html[idx: idx + PINNED_SCAN]
    # 按卡片边界切分，保证顺序与页面显示一致
    cards = seg.split("js-pinned-item-list-item")
    pattern = r'href="/' + re.escape(username) + r'/([A-Za-z0-9._-]+)"'
    names, seen = [], set()
    for card in cards:
        m = re.search(pattern, card)
        if not m:
            continue
        full = "%s/%s" % (username, m.group(1))
        if full not in seen:
            seen.add(full)
            names.append(full)
    return names


def collect(client, cfg, verbose=True):
    gh = cfg["accounts"]["github"]
    user = gh["username"]
    result = {"ok": False, "items": [], "collections": [], "profile": None}

    try:
        profile = client.get_json("https://api.github.com/users/%s" % user)
    except Exception as e:  # noqa: BLE001
        result["error"] = "用户信息获取失败：%s" % e
        return result

    repos = []
    for page in range(1, 4):
        try:
            batch = client.get_json(
                "https://api.github.com/users/%s/repos?per_page=100&page=%d&sort=pushed&type=owner"
                % (user, page))
        except Exception as e:  # noqa: BLE001
            result["error"] = "仓库列表获取失败：%s" % e
            break
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break

    pinned_names = []
    try:
        html = client.get(gh["profileUrl"], headers={"Accept": "text/html"})
        pinned_names = parse_pinned(html, user)
    except Exception as e:  # noqa: BLE001
        if verbose:
            print("    ! pinned 解析失败（不影响其它数据）：%s" % e)

    if verbose:
        print("    仓库 %d 个，pinned %d 个：%s" % (len(repos), len(pinned_names),
                                              ", ".join(pinned_names) or "无"))

    result["profile"] = {
        "platform": "github",
        "name": profile.get("name") or user,
        "handle": user,
        "avatar": profile.get("avatar_url"),
        "url": profile.get("html_url"),
        "bio": M.clean_text(profile.get("bio"), 160),
        "stats": {
            "repos": profile.get("public_repos"),
            "followers": profile.get("followers"),
            "following": profile.get("following"),
        },
        "since": M.iso(None) if not profile.get("created_at") else profile["created_at"][:10],
    }

    pinned_set = set(pinned_names)
    for r in repos:
        if r.get("fork") and r["full_name"] not in pinned_set:
            continue  # 非精选的 fork 不进列表，避免噪声
        full = r["full_name"]
        order = pinned_names.index(full) if full in pinned_set else 999
        result["items"].append(M.item(
            "github", r["id"], M.PROJECT,
            r["name"],
            r["html_url"],
            coverRemote=None,
            publishedAt=r.get("pushed_at") or r.get("created_at"),
            description=M.clean_text(r.get("description") or r.get("name"), 200),
            tags=[t for t in [r.get("language")] if t] + list(r.get("topics") or [])[:4],
            stats={
                "stars": r.get("stargazers_count"),
                "forks": r.get("forks_count"),
                "issues": r.get("open_issues_count"),
                "watchers": r.get("watchers_count"),
            },
            pinned=(full in pinned_set),
            extra={
                "fullName": full,
                "homepage": r.get("homepage"),
                "defaultBranch": r.get("default_branch"),
                "sizeKb": r.get("size"),
                "archived": r.get("archived"),
                "createdAt": r.get("created_at"),
                "pinOrder": order,
                "topics": list(r.get("topics") or []),
            },
        ))

    result["ok"] = True
    return result
