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

## 播放器

**音频：完全自建。** 构建期把每首歌的音频直链与歌词取好，放进
`assets/player-data.json`（42/43 首有直链，35 首有歌词，其中 26 首带翻译/对译）。
前端用原生 `<audio>` 播放，界面全部自己画：模糊海报背景、大封面、歌名/专辑、
自绘进度条与音量、上一首/下一首、**动态歌词**（当前行高亮并居中滚动，点某行可跳转）。

### 歌词的三种排布，统一按「正文 + 译文」处理

| 排布 | 例子 | 处理 |
|---|---|---|
| `lrc` 正文 + `tlyric` 译文（各带时间戳） | 日语原曲 + 吴语翻译 | 按时间对齐 |
| `lrc` / `tlyric` 都无时间戳 | 吴语汉字 / 拼音 | 按行号对齐 |
| **译文内联在 `lrc` 里，与正文行交替** | 汉字行下一行就是拼音，`tlyric` 为空 | 自动抽取（见下） |

第三种由 `splitInlineTranslation()` 识别：把「不含任何 CJK、只由拉丁字母/数字/标点组成」的行
抽出来当译文，挂到相邻正文行下面。为避免把**真正的英文歌词**误判成译文，要求同时满足
「这类行占比 ≥ 25%」且「≥ 60% 是紧跟在正文行后面的交替结构」两条特征，
两条不满足就原样保留。单元测试覆盖了这两种反例。

**歌词区顶部有「译文」开关，默认开启。** 开启时按钮变为青光色并在右下角带一个小勾；
点一下关闭（隐藏所有译文行、去掉小勾），再点恢复。选择记在 `localStorage`，下次打开沿用。
没有译文的曲目会自动隐藏这个按钮。

> 吴语拼音在本站一律按「译文」处理——它在网易云歌词栏里本来也是以翻译的形式呈现的。

其他要点：

- 有 5 首是**未同步歌词**（只有纯文本），照样分行完整显示，只是不做高亮跟随
- 直链失效或本就取不到 → 自动回落官方播放器，并在界面里说明原因
- 音频直链带签名时效（路径里含生成时间），所以**每次构建都会重新取一遍**，
  定时任务每 3 小时刷新一次

**视频：保持官方嵌入。** B 站播放器是跨域 iframe，读不到它的 DOM、不支持 postMessage，
官方也没有隐藏品牌或替换控件的参数——遮罩只能做出个半成品，所以不做包装。
我们在弹窗层的标题栏与底部操作区就是「我们的外壳」。
只保留官方参数 `hideCoverInfo=1`（隐藏封面信息浮层）、`danmaku=0`、`high_quality=1`。

## 体积（实测，gzip 后）

| 内容 | 大小 | 何时加载 |
|---|---|---|
| HTML（首页 / 音乐页） | 16 KB / 8 KB | 首屏 |
| CSS | 8 KB | 首屏 |
| JS | 11 KB | 首屏 |
| 主字体（霞鹜文楷子集） | 278 KB | 首屏 |
| **首屏合计** | **约 313 KB** | |
| `player-data.json`（直链＋歌词） | 73 KB | **点播放时才取** |
| 歌词字体 | 607 KB | **播放器打开时才下载** |

歌词字体单独切一份是因为歌词里吴语方言字、拼音标注太多，混进主字体首屏会翻倍。
浏览器只在真的有元素用到某个 `@font-face` 时才下载它，所以播放器没打开就不会下载。
觉得 607 KB 不划算的话，把 `config/site.json` 的 `player.lyricFont` 设为 `false`
即可让歌词回落到主字体（省掉这份按需体积，代价是生僻字会用到系统字体）。

## 数据统计

`stats.html` 的数字全部由构建期快照算出（内容量、总播放、总评论、总时长、
年度发布趋势、播放/评论前 10、平台分布），随每次更新自动重算。

本站**不做访客统计**（不引第三方、也不自建计数端点），页面上没有任何追踪代码。

## 首访语言自动判断

只在**根路径**（简中首页）注入一段内联脚本，在渲染前完成判断，不会先闪中文再跳走。
判断优先级：

1. `localStorage` 里记的用户手选（点过右上角语言菜单）—— 最高优先，避免「选了简体又被弹走」
2. **浏览器语言**：`zh-TW`/`zh-HK`/`zh-MO`/含 `Hant` → 繁体；`zh`/`zh-CN`/`zh-Hans` → 简体；`ja` → 日文
   （这一步零网络请求，绝大多数中/日访客直接命中）
3. **IP 归属地**（只在浏览器语言判不出来时才查一次 `api.country.is`）：
   中国大陆 → 简体；中国香港/澳门/台湾 → 繁体；日本 → 日文
4. 其余一律 → **英文**

配置在 `config/site.json` 的 `localeDetect`，把 `enable` 设为 `false` 可完全关闭。
已覆盖 16 个场景的自动化测试（`_probe/test_detect.js`，用 node vm 跑真实注入脚本）。

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

首次**不需要**手动去 Settings 里开 Pages：
workflow 里先用 API `POST /repos/{owner}/{repo}/pages` 尝试启用，
再用 `actions/configure-pages` 的 `enablement: true` 兜底，两者任一成功即可。
启用后即为「GitHub Actions」构建方式。

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
