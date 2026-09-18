# 雪萤小驿 · SYSite

「雪螢SiqYin」的个人作品聚合站。内容来自哔哩哔哩、网易云音乐与 GitHub，
**随各平台新投稿自动更新**，不依赖手工维护。

## 快速开始

```bash
# 一键全流程（采集 → 封面 → 渲染 → 字体子集）
python scripts/build_all.py

# 分步
python scripts/collect_all.py             # 抓数据（带缓存）
python scripts/collect_all.py --no-cache  # 强制重抓
python scripts/collect_all.py --only bilibili
python scripts/build_assets.py            # 封面落地为本地 WebP
python scripts/build_site.py              # 渲染到 dist/
python scripts/build_site.py --serve      # 渲染并起本地预览
python scripts/build_font.py              # 霞鹜文楷子集化
python scripts/list_ids.py --type video   # 列出内容 id，方便填策展配置
```

产物在 `dist/`，整个目录可原样丢到任意静态托管上。

## 页面结构

每种语言各生成 8 个页面：

| 页面 | 内容 |
|---|---|
| `index.html` | 首页：精选三栏 + 各区块预览 |
| `videos.html` | 全部视频，带排序 / 筛选 / 时间轴 |
| `music.html` | 全部音乐（逐曲小卡片），带排序 / 筛选 |
| `articles.html` | 文集与全部文章 |
| `projects.html` | 开源项目，按更新时间倒序 |
| `stats.html` | 数据统计 |
| `about.html` | 关于、平台入口、数据概览 |
| `search.html` | 站内搜索（本地过滤，不请求第三方） |

首页的精选区是三栏并排：**精选视频**、**精选音乐**、**精选吴语视频**，
每栏默认露 3 条、可向下拉到前 20 名（榜单上限由 `config/site.json` 的
`featured.maxItems` 控制）。精选视频/音乐跟随排序实时变化；
精选吴语视频取自某个视频合集（`featured.wuSource`，默认「吴越春秋」），按播放量排序。

## 排序、筛选与视图

视频与音乐区块都支持下面这些操作，**全部在浏览器端完成，站点仍是纯静态**：

- **排序**：热度（左，默认）/ 投稿时间（右），可正序倒序
- **筛选**：视频按年份 + 合集；音乐按年份 + 专辑（「其他」= 未归入任何合集）
- **视图**：网格 / 时间轴（时间轴按年份插入分隔条，随排序与筛选重算）
- 几项操作互相影响，所以由同一份状态驱动、统一重算，避免折叠计数错乱

热度字段的取舍：

| 内容 | 用的字段 | 为什么 |
|---|---|---|
| B 站视频 | 播放量 | 真实且分散 |
| 网易云歌曲 | 评论数 | 官方 `popularity` 只有 5 档，43 首里 29 首并列为 10，排不出名次 |
| GitHub 项目 | Star 数 | 同时按 `pushed_at` 倒序排列 |

## 分享卡片

`scripts/build_og.py` 用霞鹜文楷为「4 种语言 × 7 个页面」生成 1200×630 的
Open Graph 卡片（共 28 张，约 31 KB/张），页面里已带
`og:*`、`twitter:card`、`canonical` 与 `hreflang`。

**注意**：`og:image` 必须是绝对地址，站点正式域名写在 `config/site.json` 的
`site.url`（当前是 `https://siqyin.github.io/SYSite`）。换域名时记得改这里。

## 数据统计与访问计数

`stats.html` 的数字全部由构建期快照算出（内容量、总播放、总评论、总时长、
年度发布趋势、播放/评论前 10、平台分布），随每次更新自动重算。

**访问计数默认关闭**，原因很实际：GitHub Pages 是纯静态托管，没有后端，
真要做访客计数必须有一个计数端点。做法是自建一个极简端点
（Cloudflare Worker + KV 免费额度就够，约 20 行代码），然后填进配置：

```json
"analytics": { "enable": true, "endpoint": "https://your-worker.workers.dev/hit", "site": "SYSite" }
```

前端只会发**一次** `GET`，`credentials: omit`、`referrerPolicy: no-referrer`，
不设 Cookie、不记录 IP、不做任何个人标识，只累加总量。
没填 endpoint 时页面会明确显示「未启用」而不是假装有数据。

## 多语言

界面文案在 `src/i18n/*.json`，四种语言各自生成独立页面（SEO 友好、无语言闪烁）：

```
dist/index.html        简体中文（默认）
dist/zh-TW/*.html      繁體中文
dist/en/*.html         English
dist/ja/*.html         日本語
```

带 `hreflang` 与右上角切换菜单。
**作品标题一律保留原语言，不翻译**；只翻译界面文案。
新增界面文案时，四份 json 要同步补齐（key 保持一致）。

## 三个平台的数据来源（均为实测结论）

| 平台 | 内容 | 接口 | 说明 |
|---|---|---|---|
| B 站 | 视频投稿 | App 端 `/x/v2/space/archive/cursor` | 需 appkey/appsec 签名，以 aid 作游标翻页 |
| B 站 | 图文 | `/x/article/up/lists` + `/x/article/list/web/articles` | **只取文集内的文章** |
| B 站 | 置顶视频 | `/x/space/top/arc` | 免签名 |
| B 站 | 视频合集 | `/x/polymer/web-space/seasons_series_list` | 作为视频的分组标签 |
| 网易云 | 歌曲 / 专辑 | `/api/artist/{id}`、`/api/artist/top/song`、`/api/song/detail` | 无需登录 |
| 网易云 | 评论数 | `/api/v1/resource/comments/R_SO_4_{id}` | 取 `total` 作热度 |
| GitHub | 仓库 | REST `/users/{u}/repos` | |
| GitHub | 精选项目 | 主页 HTML 的 pinned 区块 | 免 Token，顺序与页面一致 |

**重要**：B 站 Web 端投稿接口 `/x/space/wbi/arc/search` 已被风控（-352 / -412），
无论是否带 wbi 签名与 buvid cookie 都不可用，因此改用 App 端接口。详见适配器注释。

## 站内播放

- 视频：`player.bilibili.com` iframe（无 X-Frame-Options）
- 音频：`music.163.com/outchain/player` iframe
- 每张卡片在弹窗里都可另点按钮跳转原平台
- 播放器**只在点击时挂载、关闭即卸载**，不拖慢首屏

## 置顶的两套配置

B 站对关注者与未关注者展示不同置顶，但接口**只对外暴露一条**
（`/x/space/top/arc` 加不加 `fan=1` 返回值相同，粉丝置顶存在创作中心、需登录）。
所以本站配两套，页面上用小开关切换：

```json
"pinned": { "sets": [
  { "id": "public", "labelKey": "pin.all",  "auto": true, "items": [] },
  { "id": "fans",   "labelKey": "pin.fans", "items": ["bilibili:BV..."], "pending": false }
]}
```

## 字体策略

霞鹜文楷（24.4 MB）在构建期按**实际用字**子集化：扫描 `dist/` 下的 HTML/CSS/JS，
切成 woff2（当前约 263 KB / 1174 字）。新投稿带来的新字下次构建自动纳入。
缺字自动回落系统字体栈。刻意不扫 `search-index.json`（含只用于检索、不上屏的描述文本，
算进来字体体积会翻倍）。

## 定时自动更新

完全由 **GitHub Actions** 负责（`.github/workflows/update.yml`）：
每 3 小时（UTC cron `23 */3 * * *`）跑一遍
采集 → 封面 → 分享卡片 → 渲染 → 字体子集 → 部署到 Pages，
内容有变化才提交 `data/` 与 `src/assets/`。
也可以在 Actions 页面手动触发（workflow_dispatch）。

首次需要在仓库 **Settings → Pages → Source** 里选 **GitHub Actions**，
否则 deploy 作业会失败（采集与构建部分不受影响）。

仓库地址：https://github.com/SiqYin/SYSite
线上地址：https://siqyin.github.io/SYSite/

## 失败降级

任一平台抓取失败时，`collect_all.py` 自动沿用上一次快照里该平台的数据，
并在页脚标记为「沿用上次快照」。**站点永远不会因为某个平台接口挂掉而空白。**

## 目录结构

```
config/site.json        站点配置：账号、平台开关、资源尺寸、字体来源
data/snapshot.json      统一内容模型的快照（含时间戳与降级标记）
data/curated.json       人工策展层（置顶两套 / 隐藏 / 简介），自动抓取永不覆盖
scripts/
  lib_http.py           统一 HTTP 客户端：重试、退避、磁盘缓存、浏览器指纹
  lib_model.py          统一内容模型与快照合并
  adapter_*.py          三个平台的采集适配器
  collect_all.py        采集编排 + 失败降级
  build_assets.py       封面下载 / 压缩 / 自托管
  build_og.py           分享卡片（Open Graph 图）生成
  build_site.py         多语言多页面静态渲染
  build_font.py         字体子集化
  list_ids.py           列出内容 id，方便填策展配置
  build_all.py          一键串联全流程
src/                    模板资源（样式、脚本、四语言文案、生成物）
dist/                   构建产物（部署目录，不进仓库）
```
