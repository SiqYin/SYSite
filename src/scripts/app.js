/* 雪萤小驿 · 交互脚本
   1) 卡片点击 → 气泡弹窗内在线播放（视频走 B 站播放器，音频走网易云播放器）
   2) 排序（热度 / 投稿时间 × 正序 / 倒序），默认热度倒序
   3) 筛选（年份 / 合集 / 专辑）与视图切换（网格 / 时间轴）
   4) 「显示更多」折叠
   5) 精选栏跟随排序实时同步
   6) 语言切换、进场动画、匿名访问计数
*/
(function () {
  "use strict";

  var I18N = window.SYS_I18N || {};
  var t = function (k) {
    var cur = I18N[window.SYS_LOCALE || "zh-CN"] || I18N["zh-CN"] || {};
    var base = I18N["zh-CN"] || {};
    return cur[k] || base[k] || k;
  };

  /* ==================== 轻提示 / 顶部进度条 ==================== */
  var toastEl = document.getElementById("toast");
  var toastTimer = null;
  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, 2400);
  }

  var loadbar = document.getElementById("loadbar");
  function loadStart() {
    if (!loadbar) return;
    loadbar.classList.add("on");
    loadbar.firstElementChild.style.width = "18%";
    setTimeout(function () { if (loadbar.firstElementChild) loadbar.firstElementChild.style.width = "52%"; }, 120);
  }
  function loadEnd() {
    if (!loadbar) return;
    loadbar.firstElementChild.style.width = "100%";
    setTimeout(function () {
      loadbar.classList.remove("on");
      loadbar.firstElementChild.style.width = "0";
    }, 320);
  }

  /* ==================== 播放弹窗 ==================== */
  var mask = document.getElementById("modal");
  var modal = mask ? mask.querySelector(".modal") : null;
  var mTitle = document.getElementById("m-title");
  var mMeta = document.getElementById("m-meta");
  var mStage = document.getElementById("m-stage");
  var mFoot = document.getElementById("m-foot");
  var lastFocus = null;

  var bgmWasPlaying = false;

  function openModal(p) {
    // BGM 与站内播放互斥：打开任何弹窗（音频或视频）都暂停 BGM，关闭时恢复。
    // needsUnmute 也算「本来该在播」，否则被浏览器策略静音拦住时会再也恢复不了。
    if (bgm.audio) {
      bgmWasPlaying = !bgm.audio.paused || bgm.pendingPlay || bgm.needsUnmute;
      bgm.pendingPlay = false;
      if (!bgm.audio.paused) bgm.audio.pause();
    }
    if (!mask) return;
    lastFocus = document.activeElement;
    mTitle.textContent = p.title || "";
    mMeta.textContent = p.meta || "";
    mStage.innerHTML = '<div class="loading-note">' + t("player.loading") + "</div>";

    var foot = "";
    if (p.source) {
      foot += '<a class="pill-link primary" href="' + p.source + '" target="_blank" rel="noopener noreferrer">' +
              (p.sourceLabel || t("player.openSource")) +
              ' <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg></a>';
    }
    if (p.platform) foot += '<span class="mnote">' + p.platform + "</span>";
    mFoot.innerHTML = foot;

    mask.classList.add("open");
    document.body.style.overflow = "hidden";
    if (modal) modal.scrollTop = 0;
    setTimeout(function () { inject(p); }, 60);
  }

  function inject(p) {
    if (p.kind === "audio" && PLAYER_CFG.ownAudio && p.song) {
      // 直链和歌词是构建期取的，首次点击时才按需拉取。
      // **无论有没有直链都渲染自建播放器**：以前这里用 hasUrl 把守，一旦 player-data
      // 缺失/过期就整块换成官方 iframe，封面、歌词、分享、加入 BGM 按钮会一起消失。
      loadAudioData().then(function () { renderAudio(p); }, function () { renderAudio(p); });
      return;
    }
    renderVideoOrEmbed(p);
  }

  /* ---------------- 自有音频播放器 ----------------
     用原生 <audio> + 我们自己画的界面：海报、动态歌词、进度、上一首下一首。
     数据（音频直链 + LRC 歌词）是构建期取好放在 assets/player-data.json 里的。
     取不到直链、或播放中途报错 → 自动回落官方播放器，并在底部说明。 */
  var PLAYER_CFG = window.SYS_PLAYER || {};
  var AUDIO = {};             // songId -> {q:{档位:链接}, l:歌词, t:译文, __build:{t:构建时间}}
  var audioReady = null;

  /* 网易云「对外播放入口」：302 跳到 CDN，**带签名的是 CDN 那一跳，入口本身不过期**。
     构建期抓下来的 CDN 直链只有约 30 分钟寿命（实测线上 8/8 全部 403），
     而定时重建 + Pages CDN 缓存追不上失效速度 —— 这是「BGM 不出声 / 播放界面变外链」
     这一类问题的总根因。所以：入口地址当默认音源，构建期直链只在刚构建、还新鲜时优先。*/
  var NETEASE_OUTER = "https://music.163.com/song/media/outer/url?id=";
  var SRC_FRESH_SEC = 20 * 60;
  function stableUrl(song) { return NETEASE_OUTER + encodeURIComponent(song) + ".mp3"; }
  function srcIsFresh() {
    var b = AUDIO && AUDIO.__build;
    var ts = (b && b.ts) || 0;
    return !!ts && (Date.now() / 1000 - ts) < SRC_FRESH_SEC;
  }
  /* 音源候选链：两组互为兜底，一串试完才提示失败 */
  function srcCandidates(song) {
    var q = ((AUDIO[song] || {}).q) || {};
    var signed = [];
    for (var i = 0; i < Q_ORDER.length; i++) { if (q[Q_ORDER[i]]) signed.push(q[Q_ORDER[i]]); }
    var out = [], seen = {};
    function push(u) { if (u && !seen[u]) { seen[u] = 1; out.push(u); } }
    if (srcIsFresh()) { signed.forEach(push); push(stableUrl(song)); }
    else { push(stableUrl(song)); signed.forEach(push); }
    return out;
  }
  var pl = null;              // 当前播放列表
  var plIdx = -1;
  var currentSong = "";       // 当前曲目 id
  var qAvail = [], qLevel = "";  // 可用音质档位与当前档位
  var el = {};                // 播放器内的元素引用
  var lrcLines = [], lrcEls = [], lastLrcIdx = -1;
  var seeking = false;

  function loadAudioData() {
    if (audioReady) return audioReady;
    var url = (window.SYS_PREFIX || "") + "assets/player-data.json";
    audioReady = fetch(url).then(function (r) { return r.json(); }).then(function (j) {
      AUDIO = j || {};
      return AUDIO;
    }).catch(function () { AUDIO = {}; return AUDIO; });
    return audioReady;
  }

  function collectPlaylist() {
    var out = [];
    var nodes = document.querySelectorAll('[data-kind="audio"][data-song]');
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (n.classList.contains("is-hidden") || n.classList.contains("filtered-out")) continue;
      var im = n.querySelector(".card-cover img");
      var sb = n.querySelector(".card-sub");
      out.push({
        song: n.getAttribute("data-song"),
        title: n.getAttribute("data-title") || "",
        meta: n.getAttribute("data-meta") || "",
        cover: im ? im.getAttribute("src") : "",
        album: sb ? sb.textContent : "",
        source: n.getAttribute("data-source") || "",
        label: n.getAttribute("data-source-label") || "",
        platform: n.getAttribute("data-platform") || ""
      });
    }
    return out;
  }

  function parseLrc(text) {
    var out = [];
    if (!text) return out;
    var lines = String(text).split(/\r?\n/);
    for (var i = 0; i < lines.length; i++) {
      var m = lines[i].match(/^((?:\[\d+:\d+(?:[.:]\d+)?\])+)(.*)$/);
      if (!m) continue;
      var body = (m[2] || "").trim();
      var stamps = m[1].match(/\[(\d+):(\d+(?:[.:]\d+)?)\]/g) || [];
      for (var j = 0; j < stamps.length; j++) {
        var mm = stamps[j].match(/\[(\d+):(\d+(?:[.:]\d+)?)\]/);
        if (!mm) continue;
        var t = parseInt(mm[1], 10) * 60 + parseFloat(mm[2].replace(":", "."));
        if (body) out.push({ t: t, s: body });
      }
    }
    if (out.length) {
      out.sort(function (a, b) { return a.t - b.t; });
      return out;
    }
    // 未同步歌词：网易云有部分曲目只提供纯文本（本站有几首还带吴语拼音对照）。
    // 这类没有时间戳，就整段显示、不做高亮跟随，但绝不能当成「没有歌词」丢掉。
    for (var k = 0; k < lines.length; k++) {
      var s = lines[k].replace(/\[[^\]]*\]/g, "").replace(/\u00a0/g, " ").trim();
      if (s) out.push({ t: null, s: s });
    }
    return out;
  }

  /* 判断「正文 + 翻译」形态的通用规则。

     网易云上常见三种排布：
     1. lrc 是正文、tlyric 是翻译（各带时间戳）→ 交给 mergeTrans 按时间对齐；
     2. lrc / tlyric 都无时间戳（纯文本）→ 按行号对齐；
     3. 翻译（本站多是吴语拼音）直接写在 lrc 里，与汉字正文行交替出现、tlyric 为空
        → 需要把这类纯拉丁行抽出来当译文挂到相邻正文行下面。

     第 3 种靠两个特征识别，避免把真正的英文歌词误判成译文：
       a) 该行不含任何 CJK/假名/谚文，且只由拉丁字母、数字、常用标点组成；
       b) 这类行在整段里占比不低，且大多是「上一行是正文」的交替结构。
     两条都满足才当译文处理。 */
  var CJK_RE = /[\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]/;
  var LATIN_ONLY_RE = /^[A-Za-z0-9\s'’\u00b7.,:;!?()[\]\-_/]+$/;

  function isLatinLine(s) {
    return s.length >= 4 && !CJK_RE.test(s) && LATIN_ONLY_RE.test(s);
  }

  function splitInlineTranslation(lines) {
    if (!lines.length || lines[0].t !== null) return lines;   // 只处理无时间戳的纯文本
    var latinIdx = [];
    for (var i = 0; i < lines.length; i++) if (isLatinLine(lines[i].s)) latinIdx.push(i);
    if (!latinIdx.length) return lines;

    var adjacent = 0;
    for (var j = 0; j < latinIdx.length; j++) {
      var k = latinIdx[j];
      if (k > 0 && CJK_RE.test(lines[k - 1].s) && latinIdx.indexOf(k - 1) < 0) adjacent++;
    }
    if (adjacent / latinIdx.length < 0.6 || latinIdx.length / lines.length < 0.25) {
      return lines;   // 更像真的英文歌词，原样保留
    }

    var out = [];
    var isLatin = {};
    for (var a = 0; a < latinIdx.length; a++) isLatin[latinIdx[a]] = true;
    for (var m = 0; m < lines.length; m++) {
      if (isLatin[m]) {
        // 挂到最近的一条还没有译文的正文行上
        for (var back = out.length - 1; back >= 0; back--) {
          if (!out[back].tr) { out[back].tr = lines[m].s; break; }
        }
      } else {
        out.push({ t: lines[m].t, s: lines[m].s });
      }
    }
    return out;
  }

  function mergeTrans(main, trans) {
    if (!trans || !trans.length || !main.length) return main;
    // 未同步歌词按行号对齐（两侧都没有时间戳）
    if (main[0].t === null) {
      for (var i = 0; i < main.length && i < trans.length; i++) main[i].tr = trans[i].s;
      return main;
    }
    // 同步歌词：取时间最接近的一行挂上去
    for (var a = 0; a < main.length; a++) {
      var best = null, bestD = 999;
      for (var b = 0; b < trans.length; b++) {
        if (trans[b].t === null) continue;
        var d = Math.abs(trans[b].t - main[a].t);
        if (d < bestD) { bestD = d; best = trans[b]; }
      }
      if (best && bestD <= 0.6) main[a].tr = best.s;
    }
    return main;
  }

  function fmtTime(s) {
    if (!isFinite(s) || s < 0) s = 0;
    var m = Math.floor(s / 60), sec = Math.floor(s % 60);
    return m + ":" + (sec < 10 ? "0" : "") + sec;
  }

  function icon(name) {
    var p = {
      play: '<path d="M8 5v14l11-7z"/>',
      pause: '<path d="M6 5h4v14H6zM14 5h4v14h-4z"/>',
      prev: '<path d="M6 6h2v12H6zM20 6v12l-9-6z"/>',
      next: '<path d="M16 6h2v12h-2zM4 6l9 6-9 6z"/>',
      volume: '<path d="M4 9h3l4-4v14l-4-4H4zM15 8.5a5 5 0 0 1 0 7v-2a3 3 0 0 0 0-3z"/>',
      mute: '<path d="M4 9h3l4-4v14l-4-4H4zM16 9l4 6M20 9l-4 6"/>'
    };
    return '<svg viewBox="0 0 24 24">' + (p[name] || "") + "</svg>";
  }

  function renderAudio(p) {
    var tpl =
      // 上方大气泡：播放器主体
      '<div class="op-bubble op-main" id="op">' +
      '  <div class="op-bg" id="op-bg"></div><div class="op-scrim"></div>' +
      '  <div class="op-player">' +
      '    <span class="op-art"><img id="op-art" alt=""></span>' +
      '    <div class="op-pinfo">' +
      '      <h4 class="op-title" id="op-title"></h4>' +
      '      <p class="op-sub" id="op-sub"></p>' +
      '      <span class="op-seek" id="op-seek"><span class="op-track"><span class="op-fill" id="op-fill"></span></span><span class="op-knob" id="op-knob"></span></span>' +
      '      <div class="op-btns">' +
      '        <span class="op-time" id="op-cur">0:00</span>' +
      '        <button class="op-btn" id="op-prev" type="button" aria-label="prev">' + icon("prev") + "</button>" +
      '        <button class="op-btn main" id="op-toggle" type="button" aria-label="play">' + icon("play") + "</button>" +
      '        <button class="op-btn" id="op-next" type="button" aria-label="next">' + icon("next") + "</button>" +
      '        <span class="op-time" id="op-dur">0:00</span>' +
      '        <button class="op-btn" id="op-vol" type="button" aria-label="mute">' + icon("volume") + "</button>" +
      '        <span class="op-seek op-vol" id="op-volbar"><span class="op-track"><span class="op-fill" id="op-volfill"></span></span><span class="op-knob" id="op-volknob"></span></span>' +
      "      </div>" +
      '    </div>' +
      "  </div>" +
      "</div>" +
      // 下方小气泡：歌词
      '<div class="op-bubble op-lybubble">' +
      '  <div class="op-lyhead">' +
      '    <span class="op-lylabel">' + esc(t("player.lyrics")) + "</span>" +
      '    <button class="op-tr-toggle" id="op-tr" type="button" aria-pressed="true">' +
      "      <span>" + esc(t("player.translation")) + "</span>" +
      '      <span class="op-check"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6L9 17l-5-5"/></svg></span>' +
      "    </button>" +
      '    <span class="op-q" id="op-q"></span>' +
      "  </div>" +
      '  <div class="op-lybody">' +
      '    <div class="op-lyrics" id="op-lyrics"></div>' +
      '    <div class="op-lydrag" id="op-lydrag" title="' + esc(t("player.lyrics")) + '">' +
      '      <span class="op-lydrag-track"></span>' +
      '      <span class="op-lydrag-knob" id="op-lydrag-knob"></span>' +
      "    </div>" +
      "  </div>" +
      "</div>";
    mStage.innerHTML = tpl;

    el = {
      root: document.getElementById("op"),
      bg: document.getElementById("op-bg"),
      art: document.getElementById("op-art"),
      title: document.getElementById("op-title"),
      sub: document.getElementById("op-sub"),
      lyrics: document.getElementById("op-lyrics"),
      trBtn: document.getElementById("op-tr"),
      qBar: document.getElementById("op-q"),
      prev: document.getElementById("op-prev"),
      toggle: document.getElementById("op-toggle"),
      next: document.getElementById("op-next"),
      cur: document.getElementById("op-cur"),
      dur: document.getElementById("op-dur"),
      seek: document.getElementById("op-seek"),
      fill: document.getElementById("op-fill"),
      knob: document.getElementById("op-knob"),
      vol: document.getElementById("op-vol"),
      volbar: document.getElementById("op-volbar"),
      volfill: document.getElementById("op-volfill"),
      volknob: document.getElementById("op-volknob")
    };

    pl = collectPlaylist();
    plIdx = 0;
    for (var i = 0; i < pl.length; i++) if (pl[i].song === p.song) { plIdx = i; break; }

    // 音源：原生 audio。不需要 CORS（只是播放，不读音频数据）
    el.audio = document.createElement("audio");
    el.audio.preload = "metadata";
    el.audio.volume = 0.9;
    el.root.appendChild(el.audio);
    bindAudioEvents();

    load(p);
    el.audio.play().catch(function () { /* 自动播放被拦截时保持暂停态 */ });
  }

  function bindAudioEvents() {
    var a = el.audio;
    a.addEventListener("timeupdate", function () { if (!seeking) syncProgress(); syncLyrics(); });
    a.addEventListener("loadedmetadata", function () {
      el.dur.textContent = fmtTime(a.duration);
      syncProgress();
    });
    a.addEventListener("play", function () { el.toggle.innerHTML = icon("pause"); });
    a.addEventListener("pause", function () { el.toggle.innerHTML = icon("play"); });
    a.addEventListener("ended", function () { nextTrack(1); });
    a.addEventListener("error", function () {
      // closeModal 拆除 src 时也会触发 error，此时不算失败
      if (!a.src || el._teardown) return;
      var cands = el._cands || [];
      el._ci = (el._ci || 0) + 1;
      // 1) 沿候选链换下一个音源（稳定接口 ↔ 构建期直链，互为兜底）
      if (el._ci < cands.length) {
        a.src = cands[el._ci];
        a.load();
        a.play().catch(function () {});
        return;
      }
      // 2) 候选链用尽：可能拿到的是浏览器缓存里的旧 player-data，强制重拉一次再试
      if (!a._refetched) {
        a._refetched = true;
        audioReady = null;
        AUDIO = {};
        loadAudioData().then(function () {
          el._cands = srcCandidates(currentSong);
          el._ci = 0;
          if (el._cands.length) {
            a.src = el._cands[0];
            a.load();
            a.play().catch(function () {});
          } else {
            showPlayerProblem(t("player.notPlayable"));
          }
        });
        return;
      }
      showPlayerProblem(t("player.streamFail"));
    });
    a.addEventListener("loadedmetadata", function () {
      a._tries = 0;          // 成功载入就清零重试计数
      el._ci = 0;
      el._cands = el._cands || [];
      a._refetched = false;
      el.dur.textContent = fmtTime(a.duration);
      syncProgress();
    });

    el.toggle.addEventListener("click", function () {
      if (a.paused) a.play().catch(function () {}); else a.pause();
    });
    el.prev.addEventListener("click", function () { nextTrack(-1); });
    el.next.addEventListener("click", function () { nextTrack(1); });
    el.vol.addEventListener("click", function () {
      a.muted = !a.muted;
      el.vol.innerHTML = icon(a.muted ? "mute" : "volume");
    });
    bindSeek(el.seek, function (ratio) { if (isFinite(a.duration)) a.currentTime = a.duration * ratio; });
    bindSeek(el.volbar, function (ratio) { a.muted = false; el.vol.innerHTML = icon("volume"); a.volume = Math.max(0, Math.min(1, ratio)); paintVol(); });

    if (el.trBtn) {
      el.trBtn.addEventListener("click", function () {
        trOn = !trOn;
        try { localStorage.setItem("sys-lyrics-tr", trOn ? "1" : "0"); } catch (e) {}
        paintTrState();
      });
    }
    bindLyricsDrag();
  }

  /* 歌词右侧拖拽控件：拖动 → 按比例跳转歌曲时间 */
  function bindLyricsDrag() {
    var bar = document.getElementById("op-lydrag");
    if (!bar) return;
    var knob = document.getElementById("op-lydrag-knob");
    function ratioOf(ev) {
      var r = bar.getBoundingClientRect();
      return Math.max(0, Math.min(1, (ev.clientY - r.top) / (r.height || 1)));
    }
    bar.addEventListener("pointerdown", function (ev) {
      ev.preventDefault();
      bar.setPointerCapture && bar.setPointerCapture(ev.pointerId);
      function seek(r) {
        var a = el.audio;
        if (a && isFinite(a.duration)) a.currentTime = a.duration * r;
        if (knob) knob.style.top = (r * 100) + "%";
      }
      seek(ratioOf(ev));
      function move(e2) { seek(ratioOf(e2)); }
      function up() {
        bar.removeEventListener("pointermove", move);
        bar.removeEventListener("pointerup", up);
      }
      bar.addEventListener("pointermove", move);
      bar.addEventListener("pointerup", up);
    });
  }

  /* 译文开关：默认开。开启时按钮变色并在右下角带一个小勾，关闭则去掉并隐藏所有译文行。 */
  var trOn = true;
  try { if (localStorage.getItem("sys-lyrics-tr") === "0") trOn = false; } catch (e) {}

  function paintTrState() {
    if (!el.root) return;
    el.root.classList.toggle("no-tr", !trOn);
    if (el.trBtn) {
      el.trBtn.classList.toggle("on", trOn);
      el.trBtn.setAttribute("aria-pressed", trOn ? "true" : "false");
      el.trBtn.title = t("player.trHint");
    }
  }

  function paintVol() {
    if (!el || !el.audio) return;
    var v = el.audio.muted ? 0 : el.audio.volume;
    el.volfill.style.width = (v * 100) + "%";
    el.volknob.style.left = (v * 100) + "%";
  }

  function bindSeek(bar, onRatio) {
    if (!bar) return;
    function ratioOf(ev) {
      var r = bar.getBoundingClientRect();
      return Math.max(0, Math.min(1, (ev.clientX - r.left) / (r.width || 1)));
    }
    bar.addEventListener("pointerdown", function (ev) {
      bar.classList.add("dragging");
      onRatio(ratioOf(ev));
      bar.setPointerCapture && bar.setPointerCapture(ev.pointerId);
      function move(e2) { onRatio(ratioOf(e2)); }
      function up() {
        bar.classList.remove("dragging");
        bar.removeEventListener("pointermove", move);
        bar.removeEventListener("pointerup", up);
      }
      bar.addEventListener("pointermove", move);
      bar.addEventListener("pointerup", up);
    });
  }

  function syncProgress() {
    if (!el || !el.audio) return;
    var a = el.audio;
    var d = a.duration || 0;
    var r = d ? (a.currentTime / d) * 100 : 0;
    el.fill.style.width = r + "%";
    el.knob.style.left = r + "%";
    el.cur.textContent = fmtTime(a.currentTime);
    var dk = document.getElementById("op-lydrag-knob");
    if (dk && d) dk.style.top = (r) + "%";
    if (d && el.dur.textContent === "0:00") el.dur.textContent = fmtTime(d);
  }

  /* 音质档位：与网易云一致（标准/较高/极高/无损）。
     请求某个档位但曲目没有时，接口会自动降级并返回实际码率，
     所以构建期就按「返回的实际码率」归档，前端只列真正存在的档位。 */
  var Q_ORDER = ["lossless", "320", "192", "128"];

  function load(item) {
    currentSong = item.song;
    currentItem = item;
    var d = AUDIO[item.song] || {};
    var q = d.q || {};
    mTitle.textContent = item.title;
    mMeta.textContent = [item.album, item.meta].filter(Boolean).join(" · ");
    el.title.textContent = item.title;
    el.sub.textContent = [item.album, item.platform].filter(Boolean).join(" · ");
    if (item.cover) { el.art.src = item.cover; el.bg.style.backgroundImage = "url(" + item.cover + ")"; }
    el.prev.disabled = pl.length < 2;
    el.next.disabled = pl.length < 2;

    // 歌词：优先用 tlyric 当译文；没有 tlyric 时，尝试把内联在正文里的拼音抽出来当译文
    var mainLines = parseLrc(d.l);
    var transLines = parseLrc(d.t);
    var lines = transLines.length ? mergeTrans(mainLines, transLines)
                                  : splitInlineTranslation(mainLines);
    lrcLines = lines; lrcEls = []; lastLrcIdx = -1;
    var hasTr = lines.some(function (x) { return x.tr; });
    if (!lines.length) {
      el.lyrics.innerHTML = '<p class="op-empty">' + esc(t("player.noLyric")) + "</p>";
      if (el.trBtn) el.trBtn.classList.add("is-hidden");
    } else {
      if (el.trBtn) el.trBtn.classList.toggle("is-hidden", !hasTr);
      el.lyrics.innerHTML = lines.map(function (ln, i) {
        return '<div class="op-line" data-i="' + i + '"><span class="op-txt">' + esc(ln.s) + "</span>" +
               (ln.tr ? '<span class="op-tr">' + esc(ln.tr) + "</span>" : "") + "</div>";
      }).join("");
      var nodes = el.lyrics.querySelectorAll(".op-line");
      for (var i = 0; i < nodes.length; i++) {
        lrcEls.push(nodes[i]);
        (function (n, idx) {
          n.addEventListener("click", function () {
            if (lrcLines[idx].t === null) return;   // 未同步歌词不能跳转
            el.audio.currentTime = lrcLines[idx].t;
          });
        })(nodes[i], i);
      }
    }
    paintTrState();

    // 音源：取可用档位里最高的做默认，前端可切换
    qAvail = Q_ORDER.filter(function (k) { return q[k]; });
    if (el.qBar) {
      var labels = { "lossless": t("q.lossless"), "320": t("q.320"), "192": t("q.192"), "128": t("q.128") };
      el.qBar.innerHTML = qAvail.map(function (k) {
        return '<button class="op-q-btn" type="button" data-q="' + k + '">' + esc(labels[k]) + "</button>";
      }).join("");
      var btns = el.qBar.querySelectorAll(".op-q-btn");
      for (var i = 0; i < btns.length; i++) {
        (function (b) {
          b.addEventListener("click", function () { setQuality(b.getAttribute("data-q")); });
        })(btns[i]);
      }
      el.qBar.classList.toggle("is-hidden", qAvail.length < 2);
    }
    qLevel = qAvail[0] || "";
    el._cands = srcCandidates(item.song);
    el._ci = 0;
    el.audio._refetched = false;
    if (el._cands.length) {
      el.audio.src = el._cands[0];
      el.audio.load();
      el.root.classList.remove("op-failed");
      removeFallbackNote();
      paintQ();
    } else {
      showPlayerProblem(t("player.notPlayable"));
    }
    paintVol();
    mFoot.innerHTML = buildFoot(item);

    var sh = document.getElementById("btn-share");
    if (sh) sh.addEventListener("click", function () { shareCardOf(item); });
    var ba = document.getElementById("btn-bgm-add");
    if (ba) {
      // 检查是否已在播放单
      loadBgmMeta(function () {
        var inList = bgm.list.some(function(m){ return m.song === item.song; });
        if (inList) { ba.textContent = t("bgm.already"); ba.classList.add("bgm-added"); ba.disabled = true; }
      });
      ba.addEventListener("click", function () { bgmAdd(item.song, ba); });
    }
  }

  function paintQ() {
    if (!el.qBar) return;
    var btns = el.qBar.querySelectorAll(".op-q-btn");
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle("on", btns[i].getAttribute("data-q") === qLevel);
    }
  }

  /* 切音质：保住当前进度与播放状态，只换音源 */
  function setQuality(level) {
    var q = ((AUDIO[currentSong] || {}).q) || {};
    if (!level || !q[level] || level === qLevel) return;
    var a = el.audio;
    if (!a) return;
    var t = a.currentTime || 0;
    var playing = !a.paused;
    qLevel = level;
    paintQ();
    // 选定档位排在最前，其余候选（含稳定接口）跟在后面兜底
    var rest = srcCandidates(currentSong).filter(function (u) { return u !== q[level]; });
    el._cands = [q[level]].concat(rest);
    el._ci = 0;
    a._refetched = false;
    a.src = q[level];
    a.load();
    a.currentTime = t;
    if (playing) a.play().catch(function () {});
  }

  function buildFoot(item) {
    var s = "";
    if (item.source) {
      s += '<a class="pill-link primary" href="' + attr(item.source) + '" target="_blank" rel="noopener noreferrer">' +
           (item.label || t("player.openSource")) +
           ' <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg></a>';
    }
    if (item.platform) s += '<span class="mnote">' + esc(item.platform) + "</span>";
    // 分享：生成带二维码的分享小卡（观看/收听按钮右侧）
    s += '<button class="pill-link" id="btn-share" type="button">' + esc(t("share.title")) + "</button>";
    if (item.song) {
      s += '<button class="pill-link" id="btn-bgm-add" type="button">' + esc(t("bgm.add")) + "</button>";
    }
    return s;
  }


  function nextTrack(step) {
    if (!el || !el.audio) return;
    if (!pl || pl.length < 2) return;
    plIdx = (plIdx + step + pl.length) % pl.length;
    lastLrcIdx = -1;
    load(pl[plIdx]);
    el.audio.play().catch(function () {});
  }

  function syncLyrics() {
    if (!el || !el.audio) return;
    if (!lrcLines.length || lrcLines[0].t === null) return;   // 未同步歌词不做高亮跟随
    var t = el.audio.currentTime + 0.15;
    var idx = -1;
    for (var i = 0; i < lrcLines.length; i++) {
      if (lrcLines[i].t <= t) idx = i; else break;
    }
    if (idx === lastLrcIdx) return;
    if (lrcEls[lastLrcIdx]) lrcEls[lastLrcIdx].classList.remove("on");
    lastLrcIdx = idx;
    if (lrcEls[idx]) {
      lrcEls[idx].classList.add("on");
      var box = el.lyrics;
      var want = lrcEls[idx].offsetTop - box.clientHeight / 2 + lrcEls[idx].offsetHeight / 2;
      box.scrollTo({ top: Math.max(0, want), behavior: "smooth" });
    }
  }

  /* 直链是构建期取的、带签名时效；一旦失效（或本来就没有）就回落官方播放器 */
  /* 播放失败时的「问题态」：**保留自建播放器**（封面/歌词/音质/分享/加入 BGM 全在），
     只在气泡底部加一条说明 + 「重试」「用官方播放器」两个入口。
     官方播放器只在用户主动点的时候、以附加块的形式出现在下方，绝不替换自建界面。*/
  function showPlayerProblem(note) {
    if (!el || !el.root) return;
    el.root.classList.add("op-failed");
    try { if (el.audio) el.audio.pause(); } catch (e) {}
    removeFallbackNote();
    var box = document.createElement("div");
    box.className = "op-fallback-note";
    var txt = document.createElement("span");
    txt.className = "op-fn-text";
    txt.textContent = note;
    box.appendChild(txt);
    var rb = document.createElement("button");
    rb.type = "button";
    rb.className = "op-fn-btn";
    rb.textContent = t("player.retry");
    rb.addEventListener("click", function () { retryPlay(); });
    box.appendChild(rb);
    if (currentItem && (currentItem.embed || currentItem.song)) {
      var ob = document.createElement("button");
      ob.type = "button";
      ob.className = "op-fn-btn";
      ob.textContent = t("player.useOfficial");
      ob.addEventListener("click", function () { embedOfficial(currentItem); });
      box.appendChild(ob);
    }
    el.root.appendChild(box);
  }

  function retryPlay() {
    var a = el && el.audio;
    if (!a) return;
    removeFallbackNote();
    el.root.classList.remove("op-failed");
    el._cands = srcCandidates(currentSong);
    el._ci = 0;
    a._refetched = false;
    if (!el._cands.length) { showPlayerProblem(t("player.notPlayable")); return; }
    a.src = el._cands[0];
    a.load();
    a.play().catch(function () {});
  }

  /* 把官方播放器作为「附加块」插到自建界面下方（不替换任何东西） */
  function embedOfficial(item) {
    if (!item) return;
    var url = item.embed || (item.song
      ? "https://music.163.com/outchain/player?type=2&auto=1&height=66&id=" + encodeURIComponent(item.song)
      : "");
    if (!url) return;
    var old = mStage.querySelector(".op-embed");
    if (old && old.parentNode) old.parentNode.removeChild(old);
    var wrap = document.createElement("div");
    wrap.className = "op-embed";
    wrap.innerHTML = '<iframe src="' + attr(url) + '" allow="autoplay" referrerpolicy="no-referrer" ' +
                     'frameborder="0" scrolling="no" title="' + attr(item.title || "") + '"></iframe>';
    mStage.appendChild(wrap);
    wrap.scrollIntoView && wrap.scrollIntoView({ block: "nearest" });
  }

  function fallbackToOfficial(note) { showPlayerProblem(note); }

  function removeFallbackNote() {
    var n = mStage.querySelector(".op-fallback-note");
    if (n) n.remove();
  }

  /* ---------------- 视频 / 兜底：官方嵌入原样 ----------------
     视频不做任何包装：官方播放器是跨域 iframe，读不到它的 DOM，
     也不支持 postMessage，官方也没有隐藏品牌或替换控件的参数。
     与其用色块遮出个半成品，不如保持官方嵌入的本色。
     我们自己的界面在弹窗的标题栏与底部操作区（打开原平台），那一层就是「我们的播放器」。 */
  function renderVideoOrEmbed(p) {
    if (!p.embed) {
      mStage.innerHTML = '<div class="loading-note">' + t("player.noEmbed") + "</div>";
      return;
    }
    loadStart();
    if (p.kind === "audio") {
      mStage.innerHTML = '<iframe class="audio-frame" src="' + attr(p.embed) + '" allow="autoplay" ' +
        'referrerpolicy="no-referrer" title="' + attr(p.title) + '" onload="window.__sysLoadEnd()"></iframe>';
    } else {
      mStage.innerHTML = '<div class="ratio"><iframe src="' + attr(p.embed) + '" scrolling="no" border="0" ' +
        'frameborder="no" framespacing="0" allowfullscreen="true" ' +
        'sandbox="allow-scripts allow-same-origin allow-presentation allow-popups" ' +
        'title="' + attr(p.title) + '" onload="window.__sysLoadEnd()"></iframe></div>';
    }
    setTimeout(loadEnd, 1800);
  }
  window.__sysLoadEnd = loadEnd;

  function closeModal() {
    var resume = (bgmWasPlaying || bgm.pendingPlay || bgm.needsUnmute) && bgm.enabled;
    bgmWasPlaying = false;
    bgm.pendingPlay = false;
    bgm.needsUnmute = false;
    if (!mask) return;
    mask.classList.remove("open");
    document.body.style.overflow = "";
    // 恢复 BGM 必须放在「弹窗标记已清除」之后：bgmPlayAt 看到弹窗还开着会直接让位
    if (resume && bgm.audio) {
      bgm.audio.muted = false;
      if (bgm.audio.paused || !bgm.audio.getAttribute("src")) bgmPlayAt(bgm.idx || 0);
      else bgmTryPlay(bgm.audio);
    }
    // 关闭即彻底停掉音频，避免后台继续播放
    if (el && el.audio) {
      el._teardown = true;   // 拆 src 会触发 error 事件，别当成播放失败
      try { el.audio.pause(); el.audio.removeAttribute("src"); el.audio.load(); } catch (e) {}
    }
    el = {}; lrcLines = []; lrcEls = []; lastLrcIdx = -1; pl = null; plIdx = -1;
    setTimeout(function () { mStage.innerHTML = ""; mFoot.innerHTML = ""; }, 340);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  if (mask) {
    mask.addEventListener("click", function (e) { if (e.target === mask) closeModal(); });
    var cb = mask.querySelector(".modal-close");
    if (cb) cb.addEventListener("click", closeModal);
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && mask && mask.classList.contains("open")) closeModal();
  });

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function attr(s) { return escapeHtml(s); }

  /* 事件委托：动态插入的结果卡片也能点 */
  function payloadOf(el) {
    return {
      title: el.getAttribute("data-title") || "",
      meta: el.getAttribute("data-meta") || "",
      embed: el.getAttribute("data-embed") || "",
      kind: el.getAttribute("data-kind") || "video",
      song: el.getAttribute("data-song") || "",
      source: el.getAttribute("data-source") || "",
      sourceLabel: el.getAttribute("data-source-label") || "",
      platform: el.getAttribute("data-platform") || "",
      cover: (function () {
        var im = el.querySelector(".card-cover img") || el.querySelector(".mini-thumb img");
        return im ? im.getAttribute("src") : "";
      })(),
      qr: el.getAttribute("data-qr") || "",
      copy: el.getAttribute("data-copy") === "1"
    };
  }
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-play]") : null;
    if (!el) return;
    if (ev.target.closest("a")) return;
    ev.preventDefault();
    openModal(payloadOf(el));
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    var el = ev.target.closest ? ev.target.closest("[data-play]") : null;
    if (!el) return;
    ev.preventDefault();
    openModal(payloadOf(el));
  });

  /* ==================== 区块控制器 ====================
     排序 / 筛选 / 折叠 / 时间轴会互相影响，所以统一由一个状态对象驱动，
     任何一项变化都走 applyView() 重算，避免出现「筛选后折叠计数对不上」这类问题。 */
  var sections = new WeakMap();

  function cardsOf(grid) {
    return [].slice.call(grid.children).filter(function (el) {
      return !el.classList.contains("year-mark");
    });
  }

  function stateOf(grid) {
    var st = sections.get(grid);
    if (!st) {
      st = { reveal: parseInt(grid.getAttribute("data-reveal") || "0", 10) || 0, step: 12, base: 0, mode: "grid", filters: {} };
      sections.set(grid, st);
    }
    return st;
  }

  function matches(card, name, want) {
    if (!want) return true;
    var have = card.getAttribute("data-f-" + name) || "";
    if (want === "__none__") return !have;
    return have.split("|").indexOf(want) >= 0;
  }

  function applyView(grid) {
    var st = stateOf(grid);
    var cards = cardsOf(grid);

    // 1) 筛选
    cards.forEach(function (c) {
      var ok = true;
      Object.keys(st.filters).forEach(function (name) {
        if (ok) ok = matches(c, name, st.filters[name]);
      });
      c.classList.toggle("filtered-out", !ok);
    });

    // 2) 折叠（只对通过筛选的卡片计数）
    var shown = 0;
    var total = 0;
    cards.forEach(function (c) {
      if (c.classList.contains("filtered-out")) { c.classList.add("is-hidden"); return; }
      total += 1;
      var visible = st.reveal === 0 || shown < st.reveal;
      c.classList.toggle("is-hidden", !visible);
      if (visible) shown += 1;
    });

    // 3) 时间轴年份标记
    var marks = grid.querySelectorAll(".year-mark");
    for (var i = 0; i < marks.length; i++) marks[i].remove();
    if (st.mode === "timeline") {
      var lastYear = null;
      cards.forEach(function (c) {
        if (c.classList.contains("is-hidden") || c.classList.contains("filtered-out")) return;
        var y = c.getAttribute("data-f-year") || "";
        if (y && y !== lastYear) {
          lastYear = y;
          var mark = document.createElement("div");
          mark.className = "year-mark";
          mark.innerHTML = '<span class="ym-num">' + esc(y) + '</span><span class="ym-line"></span>';
          grid.insertBefore(mark, c);
        }
      });
    }
    grid.classList.toggle("timeline", st.mode === "timeline");

    // 4) 空结果提示 + 更多按钮
    var empty = document.querySelector('[data-empty-for="' + grid.getAttribute("data-filterable") + '"]');
    if (empty) empty.classList.toggle("is-hidden", total > 0);

    var box = grid.parentElement;
    var btn = box ? box.querySelector("[data-more-btn]") : null;
    if (btn) {
      var left = total - shown;
      btn.disabled = left <= 0;
      btn.classList.toggle("more-done", left <= 0);
      var label = btn.querySelector("[data-more-label]");
      if (label) label.textContent = left <= 0 ? t("section.allShown") : t("more.expand");
    }
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* ---------------- 折叠 ---------------- */
  function bindReveal() {
    var boxes = document.querySelectorAll("[data-reveal]");
    for (var i = 0; i < boxes.length; i++) {
      (function (grid) {
        var st = stateOf(grid);
        st.reveal = parseInt(grid.getAttribute("data-reveal") || "12", 10);
        applyView(grid);

        var box = grid.parentElement;
        var btn = box ? box.querySelector("[data-more-btn]") : null;
        if (!btn) return;
        btn.addEventListener("click", function () {
          st.reveal += st.step;
          revealAnimate(grid, st);
          applyView(grid);
        });
      })(boxes[i]);
    }
  }

  function revealAnimate(grid, st) {
    var n = 0;
    cardsOf(grid).forEach(function (c) {
      if (c.classList.contains("filtered-out")) return;
      if (!c.classList.contains("revealed") && !c.classList.contains("is-hidden") && n < st.step) {
        c.classList.add("revealed");
        c.style.animationDelay = (n * 26) + "ms";
        n += 1;
      }
    });
  }

  /* ---------------- 筛选 ---------------- */
  function bindFilters() {
    var rows = document.querySelectorAll(".filter-row[data-filter]");
    for (var i = 0; i < rows.length; i++) {
      (function (row) {
        var name = row.getAttribute("data-filter");
        var host = row.closest("section") || document;
        var grid = host.querySelector("[data-filterable]");
        if (!grid) return;
        row.addEventListener("click", function (e) {
          var btn = e.target.closest(".chip-btn");
          if (!btn) return;
          var btns = row.querySelectorAll(".chip-btn");
          for (var j = 0; j < btns.length; j++) btns[j].classList.toggle("on", btns[j] === btn);
          stateOf(grid).filters[name] = btn.getAttribute("data-value");
          applyView(grid);
        });
      })(rows[i]);
    }
  }

  /* ---------------- 视图切换（网格 / 时间轴） ---------------- */
  function bindViewSwitch() {
    var switches = document.querySelectorAll("[data-view-switch]");
    for (var i = 0; i < switches.length; i++) {
      (function (sw) {
        var host = sw.closest("section") || document;
        var grid = host.querySelector("[data-filterable]");
        if (!grid) return;
        var btns = sw.querySelectorAll("[data-set-view]");
        for (var j = 0; j < btns.length; j++) {
          btns[j].addEventListener("click", function () {
            for (var k = 0; k < btns.length; k++) btns[k].classList.toggle("on", btns[k] === this);
            stateOf(grid).mode = this.getAttribute("data-set-view");
            applyView(grid);
          });
        }
      })(switches[i]);
    }
  }

  /* ---------------- 排序 ---------------- */
  function bindSort() {
    var bars = document.querySelectorAll("[data-sortbar]");
    for (var i = 0; i < bars.length; i++) {
      (function (bar) {
        var key = bar.getAttribute("data-sortbar");
        var grid = document.querySelector('[data-sortable="' + key + '"]');
        if (!grid) return;

        var modeBtns = bar.querySelectorAll("[data-set-mode]");
        var dirBtn = bar.querySelector("[data-toggle-dir]");
        var dirLabel = bar.querySelector("[data-dir-label]");

        function resort() {
          var mode = bar.getAttribute("data-mode") || "heat";
          var dir = bar.getAttribute("data-dir") || "desc";
          var field = mode === "heat" ? "data-heat" : "data-ts";
          var cards = cardsOf(grid);
          cards.sort(function (a, b) {
            var av = parseFloat(a.getAttribute(field) || "0") || 0;
            var bv = parseFloat(b.getAttribute(field) || "0") || 0;
            if (av === bv) {
              var at = parseFloat(a.getAttribute("data-ts") || "0") || 0;
              var bt = parseFloat(b.getAttribute("data-ts") || "0") || 0;
              return dir === "desc" ? bt - at : at - bt;
            }
            return dir === "desc" ? bv - av : av - bv;
          });
          cards.forEach(function (c) { grid.appendChild(c); });

          applyView(grid);
          grid.classList.remove("is-sorting");
          void grid.offsetWidth;
          grid.classList.add("is-sorting");
          setTimeout(function () { grid.classList.remove("is-sorting"); }, 420);
          refreshFeatured();
        }

        for (var j = 0; j < modeBtns.length; j++) {
          if (modeBtns[j].getAttribute("data-set-mode") === (bar.getAttribute("data-mode") || "heat")) {
            modeBtns[j].classList.add("on");
          }
          modeBtns[j].addEventListener("click", function () {
            for (var k = 0; k < modeBtns.length; k++) modeBtns[k].classList.remove("on");
            this.classList.add("on");
            bar.setAttribute("data-mode", this.getAttribute("data-set-mode"));
            resort();
          });
        }
        if (dirBtn) {
          dirBtn.addEventListener("click", function () {
            var next = (bar.getAttribute("data-dir") || "desc") === "desc" ? "asc" : "desc";
            bar.setAttribute("data-dir", next);
            dirBtn.setAttribute("data-dir", next);
            if (dirLabel) dirLabel.textContent = next === "desc" ? t("sort.desc") : t("sort.asc");
            resort();
          });
        }
      })(bars[i]);
    }
  }

  /* ==================== 精选栏跟随排序 ==================== */
  function miniFromCard(card, rank) {
    var img = card.querySelector(".card-cover img");
    var kind = card.getAttribute("data-kind") || "video";
    var title = card.getAttribute("data-title") || "";
    var meta = card.getAttribute("data-meta") || "";
    var square = kind === "audio" ? " sq" : "";
    var thumb = img ? '<span class="mini-thumb' + square + '"><img src="' + attr(img.getAttribute("src")) +
                      '" alt="" loading="lazy" decoding="async"></span>' : "";
    var rankCls = rank === 1 ? "" : (rank === 2 ? " r2" : " r3");
    return '<button class="mini" type="button" data-play="1" data-kind="' + attr(kind) + '"' +
           ' data-title="' + attr(title) + '" data-meta="' + attr(meta) + '"' +
           ' data-embed="' + attr(card.getAttribute("data-embed") || "") + '"' +
           ' data-source="' + attr(card.getAttribute("data-source") || "") + '"' +
           ' data-source-label="' + attr(card.getAttribute("data-source-label") || "") + '"' +
           ' data-platform="' + attr(card.getAttribute("data-platform") || "") + '">' +
           thumb + '<span class="mini-body"><span class="mini-title"><span class="mini-rank' + rankCls + '">' +
           rank + "</span>" + esc(title) + "</span>" +
           '<span class="mini-meta">' + esc(meta) + "</span></span></button>";
  }

  function refreshFeatured() {
    var holders = document.querySelectorAll("[data-top3]");
    for (var i = 0; i < holders.length; i++) {
      var holder = holders[i];
      var grid = document.querySelector('[data-sortable="' + holder.getAttribute("data-top3") + '"]');
      if (!grid) continue;
      var limit = parseInt(holder.getAttribute("data-top3-limit") || "20", 10);
      var cards = cardsOf(grid).filter(function (c) { return !c.classList.contains("is-hidden"); });
      // 取当前排序下真正靠前的卡片（含折叠起来但未被筛选掉的）
      if (cards.length < limit) {
        cards = cardsOf(grid).filter(function (c) { return !c.classList.contains("filtered-out"); });
      }
      var html = "";
      cards.slice(0, limit).forEach(function (c, idx) { html += miniFromCard(c, idx + 1); });
      holder.innerHTML = html;
    }
  }

  /* ==================== 语言切换 ====================
     每种语言是一份独立页面，菜单项就是普通链接。
     点击时把选择写进 localStorage —— 这样根路径的语言自动判断会尊重用户的手动选择，
     不会出现「选了简体又被自动弹回日文」这种来回跳。 */
  function bindLang() {
    var btn = document.getElementById("lang-btn");
    var menu = document.getElementById("lang-menu");
    if (!btn || !menu) return;
    var items = menu.querySelectorAll(".lang-item");
    for (var i = 0; i < items.length; i++) {
      items[i].addEventListener("click", function () {
        var code = this.getAttribute("hreflang");
        try { if (code) localStorage.setItem("sys-locale", code); } catch (e) {}
      });
    }
    btn.addEventListener("click", function (e) { e.stopPropagation(); menu.classList.toggle("open"); });
    menu.addEventListener("click", function (e) { e.stopPropagation(); });
    document.addEventListener("click", function () { menu.classList.remove("open"); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") menu.classList.remove("open"); });
  }

  /* ==================== 站内搜索 ==================== */
  function bindSearch() {
    var page = document.getElementById("search-page");
    if (!page) return;
    var input = document.getElementById("q");
    var results = document.getElementById("search-results");
    var note = document.getElementById("search-note");
    var state = { q: "", type: "", year: "" };
    var data = null;
    var LIMIT = 60;

    function mark(text, q) {
      var safe = esc(text);
      if (!q) return safe;
      var i = safe.toLowerCase().indexOf(q.toLowerCase());
      if (i < 0) return safe;
      return safe.slice(0, i) + "<em>" + safe.slice(i, i + q.length) + "</em>" + safe.slice(i + q.length);
    }

    function cardHtml(it, q) {
      var title = mark(it.t, q);
      var meta = esc(it.m);
      var cover = it.c
        ? '<div class="card-cover' + (it.k === "audio" ? " square" : "") + '">' +
          '<img src="' + attr(it.c) + '" alt="" loading="lazy" decoding="async">' +
          (it.k === "audio" && it.x ? '<span class="badge">' + esc(it.x) + "</span>" : "") + "</div>"
        : "";
      if (it.e) {
        return '<article class="card search-hit" data-play="1" data-kind="' +
          (it.k === "audio" ? "audio" : "video") + '" tabindex="0" role="button"' +
          ' data-title="' + attr(it.t) + '" data-meta="' + attr(it.m) + '"' +
          ' data-embed="' + attr(it.e) + '" data-source="' + attr(it.u) + '"' +
          ' data-source-label="' + attr(it.l) + '" data-platform="' + attr(it.pl) + '">' +
          cover + '<div class="card-body"><h3 class="card-title">' + title + "</h3>" +
          '<div class="card-meta"><span>' + meta + "</span></div></div></article>";
      }
      if (it.k === "project") {
        return '<a class="card repo-card search-hit" href="' + attr(it.u) +
          '" target="_blank" rel="noopener noreferrer"><div class="rname">' + title + "</div>" +
          '<div class="rmeta"><span>' + meta + "</span></div></a>";
      }
      return '<a class="post search-hit" href="' + attr(it.u) + '" target="_blank" rel="noopener noreferrer">' +
        '<p class="ptxt">' + title + "</p>" +
        '<div class="pmeta"><span>' + esc(it.x || "") + "</span><span>" + meta + "</span></div></a>";
    }

    function render() {
      if (!data) return;
      var q = state.q.trim();
      var ql = q.toLowerCase();
      var hit = data.filter(function (it) {
        if (state.type && it.k !== state.type) return false;
        if (state.year && String(it.d || "").slice(0, 4) !== state.year) return false;
        return !(ql && it.s.indexOf(ql) === -1);
      });
      results.className = "grid videos";
      if (!hit.length && (q || state.type || state.year)) {
        results.innerHTML = '<div class="pin-empty">' + t("search.empty") + "</div>";
        results.className = "";
      } else {
        results.innerHTML = hit.slice(0, LIMIT).map(function (it) { return cardHtml(it, q); }).join("");
      }
      note.textContent = (q || state.type || state.year)
        ? t("search.count").replace("{n}", hit.length)
        : t("search.hint");
    }

    input.addEventListener("input", function () { state.q = input.value; render(); });
    var rows = page.querySelectorAll(".filter-row");
    for (var i = 0; i < rows.length; i++) {
      (function (row) {
        var kind = row.getAttribute("data-filter");
        row.addEventListener("click", function (e) {
          var btn = e.target.closest(".chip-btn");
          if (!btn) return;
          var btns = row.querySelectorAll(".chip-btn");
          for (var j = 0; j < btns.length; j++) btns[j].classList.toggle("on", btns[j] === btn);
          state[kind] = btn.getAttribute("data-value");
          render();
        });
      })(rows[i]);
    }

    fetch(page.getAttribute("data-index")).then(function (r) { return r.json(); }).then(function (j) {
      data = j;
      render();
    }).catch(function () { note.textContent = t("search.failed"); });

    var pre = new URLSearchParams(location.search).get("q");
    if (pre) { input.value = pre; state.q = pre; }
  }

  /* ==================== 进场动画 / 顶栏 ==================== */
  function bindRise() {
    var els = document.querySelectorAll(".rise");
    if (!("IntersectionObserver" in window)) {
      for (var i = 0; i < els.length; i++) els[i].classList.add("in");
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          var el = en.target;
          setTimeout(function () { el.classList.add("in"); }, parseInt(el.getAttribute("data-delay") || "0", 10));
          io.unobserve(el);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.06 });
    for (var j = 0; j < els.length; j++) io.observe(els[j]);
  }

  function bindTopbar() {
    var bar = document.querySelector(".topbar");
    if (!bar) return;
    var onScroll = function () { bar.classList.toggle("is-stuck", window.scrollY > 8); };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    var brand = document.querySelector(".brand");
    if (brand && (location.pathname.endsWith("/") || location.pathname.endsWith("index.html"))) {
      brand.addEventListener("click", function (e) { e.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); });
    }
  }


  /* ================================================================
     分享小卡：Canvas 合成封面 + 标题 + 平台 + 二维码，长按保存到相册。
     二维码是构建期生成好的 PNG，运行时只管拼图，不引第三方库。
     ================================================================ */
  function currentPayload() {
    return currentItem || null;
  }

  // 当前播放/展示的条目（弹窗打开时记录）
  var currentItem = null;

  function shareCardOf(item) {
    if (!item) return;
    var W = 640, H = 900;
    var cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    var g = cv.getContext("2d");

    // 背景
    var grd = g.createLinearGradient(0, 0, W, H);
    grd.addColorStop(0, "#f2f8fd");
    grd.addColorStop(1, "#dce9f5");
    g.fillStyle = grd;
    g.fillRect(0, 0, W, H);

    // 顶部站点名
    g.fillStyle = "#1a5276";
    g.font = "500 30px " + getComputedStyle(document.body).fontFamily;
    g.textAlign = "center";
    g.fillText(t("site.name"), W / 2, 76);

    // 封面
    var cx = 100, cy = 110, cw = 440, ch = 440;
    function drawCover(img) {
      try {
        var r = Math.max(cw / img.width, ch / img.height);
        var dw = img.width * r, dh = img.height * r;
        g.save();
        g.beginPath();
        roundRectPath(g, cx, cy, cw, ch, 24);
        g.clip();
        g.drawImage(img, cx + (cw - dw) / 2, cy + (ch - dh) / 2, dw, dh);
        g.restore();
      } catch (e) {}
    }
    // 美观的封面占位：渐变 + 音符图标
    var coverGrd = g.createLinearGradient(cx, cy, cx + cw, cy + ch);
    coverGrd.addColorStop(0, "#2980b9");
    coverGrd.addColorStop(1, "#1a5276");
    g.fillStyle = coverGrd;
    roundRect(g, cx, cy, cw, ch, 24);
    g.fill();
    // 音符图标
    g.fillStyle = "rgba(255,255,255,0.25)";
    g.font = "120px sans-serif";
    g.textAlign = "center";
    g.fillText("♪", cx + cw / 2, cy + ch / 2 + 40);
    g.fillStyle = "rgba(255,255,255,0.5)";
    g.font = "18px sans-serif";
    g.fillText(t("site.name"), cx + cw / 2, cy + ch - 30);
    if (item.cover) {
      var im = new Image();
      im.onload = function () { drawCover(im); finish(); };
      im.onerror = function () { finish(); };
      im.src = item.cover;
    } else {
      finish();
    }

    var done = false;
    function finish() {
      if (done) return;
      done = true;
      // 标题（最多两行）
      g.fillStyle = "#1a2a3a";
      g.font = "500 30px " + getComputedStyle(document.body).fontFamily;
      g.textAlign = "center";
      var lines = wrapText(g, item.title || "", W - 120);
      var ly = cy + ch + 62;
      for (var i = 0; i < Math.min(lines.length, 3); i++) {
        g.fillText(lines[i], W / 2, ly + i * 44);
      }
      // 副标题：专辑 + 平台
      g.fillStyle = "#5b7f9e";
      g.font = "400 22px " + getComputedStyle(document.body).fontFamily;
      var sub = [item.album, item.platform].filter(Boolean).join(" · ");
      g.fillText(sub, W / 2, ly + Math.min(lines.length, 3) * 44 + 30);
      // 二维码
      var qy = H - 250;
      g.fillStyle = "#ffffff";
      roundRect(g, W / 2 - 110, qy - 14, 220, 220, 18);
      g.fill();
      if (item.qr) {
        var q = new Image();
        q.onload = function () {
          try { g.drawImage(q, W / 2 - 82, qy, 164, 164); } catch (e) {}
          tail();
        };
        q.onerror = tail;
        q.src = (window.SYS_PREFIX || "") + item.qr;
      } else {
        tail();
      }
      function tail() {
        g.fillStyle = "#5b7f9e";
        g.font = "400 20px " + getComputedStyle(document.body).fontFamily;
        g.fillText(t("share.scan"), W / 2, H - 30);
        showShareModal(cv.toDataURL("image/png"), item);
      }
    }
  }

  function roundRectPath(g, x, y, w, h, r) {
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
    return g;
  }
  function roundRect(g, x, y, w, h, r) { return roundRectPath(g, x, y, w, h, r); }

  function wrapText(g, text, maxW) {
    var out = [], cur = "";
    for (var i = 0; i < text.length; i++) {
      var test = cur + text[i];
      if (g.measureText(test).width > maxW && cur) { out.push(cur); cur = text[i]; } else { cur = test; }
    }
    if (cur) out.push(cur);
    return out;
  }

  function showShareModal(dataUrl, item) {
    var box = document.getElementById("share-modal");
    if (!box) return;
    var img = document.getElementById("share-img");
    if (img) img.src = dataUrl;
    var a = document.getElementById("share-dl");
    if (a) {
      a.href = dataUrl;
      a.download = (item && item.title ? item.title.slice(0, 40) : "share") + ".png";
    }
    box.classList.add("open");
  }

  /* ================================================================
     BGM 系统：独立音频通道 + 右上角管理面板 + 播放单（可拖拽排序）+ 四种播放顺序
     ================================================================ */
  var BGM_DEFAULT = ["3397931174", "3391836260", "3346195311", "2105851215", "2742796005"];
  var bgm = {
    audio: null,
    meta: {},          // songId -> {t, c, a}
    list: [],          // 播放单 [{song, t, c, a}]
    idx: 0,
    mode: "shuffle",   // shuffle | order | reverse | loop
    queue: [],         // 第一轮乱序队列
    firstRoundDone: false,
    enabled: true,
    roundOne: false
  };

  function bgmAsset(name) { return (window.SYS_PREFIX || "") + "assets/" + name; }

  function loadBgmMeta(cb) {
    if (Object.keys(bgm.meta).length) { cb(); return; }
    fetch(bgmAsset("bgm-meta.json")).then(function (r) { return r.json(); }).then(function (j) {
      bgm.meta = j || {};
      cb();
    }).catch(function () { cb(); });
  }

  function bgmEntry(song) {
    var m = bgm.meta[song] || {};
    return { song: song, t: m.t || song, c: m.c || "", a: m.a || "" };
  }

  function initBgm() {
    // ---------- 1) 先组播放单：全部来自本地（localStorage / 构建期常量），不等网络 ----------
    var wuIds = window.SYS_BGM_WU || [];            // 构建期注入的吴语歌单
    var stored = null;
    try { stored = JSON.parse(localStorage.getItem("sys-bgm-list") || "null"); } catch (e) {}
    var songIds = (stored && stored.length) ? stored : BGM_DEFAULT.concat(wuIds);
    var seen = {};
    bgm.list = [];
    for (var i = 0; i < songIds.length; i++) {
      if (!songIds[i] || seen[songIds[i]]) continue;
      seen[songIds[i]] = true;
      bgm.list.push(bgmEntry(songIds[i]));
    }
    bgm.initialCount = Math.min(BGM_DEFAULT.length, bgm.list.length);
    bgm.userReordered = !!stored;
    try {
      var m = localStorage.getItem("sys-bgm-mode");
      if (m) bgm.mode = m;
    } catch (e) {}
    try { bgm.enabled = localStorage.getItem("sys-bgm-off") !== "1"; } catch (e) {}

    // ---------- 2) 立刻建 audio 并起播：不依赖任何 fetch ----------
    // 旧实现把整段初始化塞在 loadBgmMeta 回调里，且音源要等 176 KB 的
    // player-data.json —— 网络一慢、文件一旧，进页面就不出声。
    if (!bgm.audio) {
      bgm.audio = document.createElement("audio");
      bgm.audio.preload = "auto";
      bgm.audio.volume = 0.55;
      bgm.audio.addEventListener("ended", function () { bgmAdvance(true); });
      bgm.audio.addEventListener("error", bgmOnError);
      bgm.audio.addEventListener("playing", function () { bgm.failStreak = 0; bgmPaintProgress(); });
      bgm.audio.addEventListener("timeupdate", bgmPaintProgress);
      bgm.audio.addEventListener("loadedmetadata", bgmPaintProgress);
      document.body.appendChild(bgm.audio);
    }
    buildQueue();
    paintBgmBtn();
    if (bgm.enabled) tryAutoStart();

    // ---------- 3) 后台补元数据（标题/封面）与播放器数据，回来刷新面板 ----------
    loadBgmMeta(function () {
      for (var j = 0; j < bgm.list.length; j++) bgm.list[j] = bgmEntry(bgm.list[j].song);
      var pt = document.getElementById("bgp-title");
      if (pt) pt.textContent = t("bgm.title");
      var ph = document.getElementById("bgp-hint");
      if (ph) ph.textContent = t("bgm.drag");
      var st2 = document.getElementById("sm-title");
      if (st2) st2.textContent = t("share.title");
      var sh2 = document.getElementById("sm-hint");
      if (sh2) sh2.textContent = t("share.hint");
      var dl = document.getElementById("share-dl");
      if (dl) dl.textContent = t("share.save");
      var sx = document.getElementById("share-x");
      if (sx && !sx._bound) {
        sx._bound = true;
        sx.addEventListener("click", function () {
          var b2 = document.getElementById("share-modal");
          if (b2) b2.classList.remove("open");
        });
      }
      renderBgmList();
      if (!bgm.uiBound) { bindBgmUi(); bgm.uiBound = true; }
      paintBgmActive();
      paintBgmBar();
    });
    loadAudioData();   // 预热：歌词 + 签名直链兜底（失败也不影响 BGM 播放）
  }

  /* 播放队列逻辑：
     - 首次进入（用户没拖拽过）→ 前 initialCount 首乱序播一轮 → 之后进入吴语歌单部分按顺序循环
     - 用户拖拽后 → 按新顺序，配合当前模式（顺序/逆序/乱序/单曲循环）播放 */
  function bgmCurrent() {
    return bgm.queue[bgm.idx] || bgm.list[0] || null;
  }

  /* 兼容旧引用 */
  function buildBgmQueue() { buildQueue(); }

  function buildQueue() {
    var list = bgm.list;
    if (bgm.userReordered) {
      bgm.queue = list.slice();
      bgm.idx = 0;
      return;
    }
    // 没拖拽过 → 前 5 首乱序，其余按顺序
    var head = list.slice(0, Math.min(bgm.initialCount, list.length));
    var tail = list.slice(Math.min(bgm.initialCount, list.length));
    for (var i = head.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = head[i]; head[i] = head[j]; head[j] = tmp;
    }
    bgm.queue = head.concat(tail);
    bgm.idx = 0;
    // 第一轮只播前 5 首（乱序），之后从吴语歌单开始按顺序循环
    bgm.roundOne = head.length;
  }

  function bgmAdvance(auto) {
    if (bgm.mode === "loop" && auto) { bgmPlayAt(bgm.idx); return; }
    // 第一轮结束：如果还在前 initialCount 首内，跳到吴语歌单部分
    if (bgm.roundOne && bgm.idx >= bgm.roundOne - 1) {
      bgm.roundOne = false;
      bgm.idx = bgm.initialCount;   // 从吴语歌单的第一首开始
      if (bgm.idx >= bgm.queue.length) bgm.idx = 0;
      bgmPlayAt(bgm.idx);
      return;
    }
    bgm.idx += 1;
    if (bgm.idx >= bgm.queue.length) {
      if (bgm.mode === "loop") { bgm.idx = bgm.initialCount; }
      else { bgm.idx = 0; }
    }
    bgmPlayAt(bgm.idx);
  }

  function bgmNext() { bgmAdvance(false); }
  function bgmPrev() {
    bgm.idx -= 1;
    if (bgm.idx < 0) bgm.idx = bgm.queue.length - 1;
    bgmPlayAt(bgm.idx);
  }
  function bgmToggle() {
    var a = bgm.audio;
    if (!a) return;
    if (a.paused) { if (!a.src) bgmPlayAt(bgm.idx || 0); else a.play().catch(function () {}); }
    else a.pause();
    paintBgmBar();
  }

  /* BGM 自动播放：不依赖任何网络请求（音源用稳定接口，见 bgmCands）。
     先试「有声自动播」——部分浏览器/站点已授权，这样进页面就有声；
     被拒则退到「静音自动播」（浏览器一律允许），并等首次用户手势开声。
     注意：手势开声不再挑三拣四，任何一次交互都要能让 BGM 出声，
     与内容播放的互斥交给 openModal/closeModal（同一手势内同步执行，不会重叠）。*/
  function tryAutoStart() {
    var a = bgm.audio;
    if (!a) return;
    bgm.needsUnmute = false;
    bgmPlayAt(0);        // 先设音源（稳定接口，不需要任何网络请求）再起播
    var unlock = function (ev) {
      if (!bgm.audio || !bgm.enabled) return;
      var tgt = ev.target;
      var onContent = tgt && tgt.closest && tgt.closest(
        "[data-play],[data-song],[data-bvid],[data-kind],.modal-mask,#bgm-btn,#bgm-panel,#share-modal,.op-bubble");
      if (onContent) {
        // 点内容：只确保「静音也在跑」，不抢声道 —— openModal 会在同一手势里暂停它
        if (bgm.audio.paused) bgm.audio.play().catch(function () {});
        return;
      }
      off();
      bgm.needsUnmute = false;
      bgm.audio.muted = false;
      if (bgm.audio.paused) bgmPlayAt(bgm.idx || 0);
      else bgm.audio.play().catch(function () {});
    };
    function off() {
      document.removeEventListener("pointerdown", unlock, true);
      document.removeEventListener("keydown", unlock, true);
      document.removeEventListener("touchstart", unlock, true);
    }
    document.addEventListener("pointerdown", unlock, true);
    document.addEventListener("keydown", unlock, true);
    document.addEventListener("touchstart", unlock, true);
  }


  /* BGM 音源候选链：稳定接口优先（不用等任何 fetch，永不过期）。 */
  function bgmCands(song) {
    var out = [stableUrl(song)], seen = {};
    seen[out[0]] = 1;
    var q = ((AUDIO[song] || {}).q) || {};
    for (var i = 0; i < Q_ORDER.length; i++) {
      var u = q[Q_ORDER[i]];
      if (u && !seen[u]) { seen[u] = 1; out.push(u); }
    }
    return out;
  }

  function bgmPlayAt(i) {
    var cur = bgm.queue[i];
    if (!cur) return;
    bgm.idx = i;
    var a = bgm.audio;
    if (!a) return;
    // 弹窗开着就别抢播（点击竞态）：标记待播，closeModal 里补
    var mm = document.querySelector(".modal-mask");
    if (mm && mm.classList.contains("open")) { bgm.pendingPlay = true; return; }
    bgm.cands = bgmCands(cur.song);
    bgm.ci = 0;
    if (!bgm.cands.length) { bgmAdvance(true); return; }
    a.src = bgm.cands[0];
    a.load();
    bgmTryPlay(a);
    paintBgmActive();
    paintBgmBar();
  }

  /* 播放 BGM：先试有声（部分浏览器/站点已授权）；被自动播放策略拒绝就退到
     静音起播（浏览器一律允许），并标记 needsUnmute；首次手势或关弹窗时开声。*/
  function bgmTryPlay(a) {
    if (!a) return;
    if (!a.muted) {
      var p = a.play();
      if (p && p.catch) p.catch(function () {
        bgm.needsUnmute = true;
        a.muted = true;
        var p2 = a.play();
        if (p2 && p2.catch) p2.catch(function () { bgm.needsUnmute = true; });
      });
      return;
    }
    var p3 = a.play();
    if (p3 && p3.catch) p3.catch(function () { bgm.needsUnmute = true; });
  }

  /* BGM 音源失败：沿候选链换源；连续多首都失败就停下，不再空转 */
  function bgmOnError() {
    var a = bgm.audio;
    if (!a || !a.getAttribute("src")) return;
    bgm.ci = (bgm.ci || 0) + 1;
    if (bgm.cands && bgm.ci < bgm.cands.length) {
      a.src = bgm.cands[bgm.ci];
      a.load();
      var pr = a.play();
      if (pr && pr.catch) pr.catch(function () {});
      return;
    }
    bgm.failStreak = (bgm.failStreak || 0) + 1;
    bgm.ci = 0;
    if (bgm.failStreak >= 3) { bgm.failStreak = 0; paintBgmBar(); return; }
    bgmAdvance(true);
  }


  function bindBgmUi() {
    var btn = document.getElementById("bgm-btn");
    if (btn) btn.addEventListener("click", function () {
      var p = document.getElementById("bgm-panel");
      if (p) p.classList.toggle("open");
    });
    var close = document.getElementById("bgm-close");
    if (close) close.addEventListener("click", function () {
      var p = document.getElementById("bgm-panel");
      if (p) p.classList.remove("open");
    });
    var prev = document.getElementById("bgm-prev");
    if (prev) prev.addEventListener("click", bgmPrev);
    var next = document.getElementById("bgm-next");
    if (next) next.addEventListener("click", function () { bgmNext(false); });
    var tg = document.getElementById("bgm-toggle");
    if (tg) tg.addEventListener("click", bgmToggle);
    var md = document.getElementById("bgm-mode");
    if (md) md.addEventListener("click", function () {
      var order = ["shuffle", "order", "reverse", "loop"];
      bgm.mode = order[(order.indexOf(bgm.mode) + 1) % order.length];
      try { localStorage.setItem("sys-bgm-mode", bgm.mode); } catch (e) {}
      buildBgmQueue();
      bgmPlayAt(0);
      paintBgmBar();
    });
    var off = document.getElementById("bgm-off");
    if (off) off.addEventListener("click", function () {
      bgm.enabled = !bgm.enabled;
      try { localStorage.setItem("sys-bgm-off", bgm.enabled ? "0" : "1"); }
      catch (e) {}
      if (bgm.enabled) { bgmPlayAt(bgm.idx || 0); }
      else if (bgm.audio) bgm.audio.pause();
      paintBgmBtn();
    });
    enableBgmDrag();
  }

  function renderBgmList() {
    var ul = document.getElementById("bgm-list");
    if (!ul) return;
    if (!bgm.list.length) {
      ul.innerHTML = '<li class="bgm-empty">' + esc(t("bgm.empty")) + "</li>";
      return;
    }
    ul.innerHTML = bgm.list.map(function (m, i) {
      return '<li data-i="' + i + '">' +
        '<span class="bgm-handle" data-drag>⠿</span>' +
        '<span class="bgm-name">' + esc(m.t) + (m.a ? '<em>' + esc(m.a) + "</em>" : "") + "</span>" +
        '<button class="bgm-del" data-del="1" type="button" aria-label="remove">×</button>' +
        "</li>";
    }).join("");
    [].slice.call(ul.querySelectorAll("[data-del]")).forEach(function (b) {
      b.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var li = b.closest("li");
        var i = parseInt(li.getAttribute("data-i"), 10);
        bgm.list.splice(i, 1);
        saveBgmList();
        renderBgmList();
        buildBgmQueue();
        bgmPlayAt(bgm.idx >= bgm.queue.length ? 0 : bgm.idx);
      });
    });
    paintBgmActive();
  }

  function saveBgmList() {
    try { localStorage.setItem("sys-bgm-list", JSON.stringify(bgm.list.map(function (m) { return m.song; }))); }
    catch (e) {}
  }

  /* 指针拖拽排序：桌面与手机都能用（HTML5 draggable 在移动端不工作） */
  function enableBgmDrag() {
    var list = document.getElementById("bgm-list");
    if (!list) return;
    var dragging = null;
    list.addEventListener("pointerdown", function (ev) {
      var h = ev.target.closest("[data-drag]");
      if (!h) return;
      dragging = h.closest("li");
      if (dragging) dragging.classList.add("dragging");
      ev.preventDefault();
    });
    list.addEventListener("pointermove", function (ev) {
      if (!dragging) return;
      var rows = [].slice.call(list.querySelectorAll("li:not(.dragging)"));
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i].getBoundingClientRect();
        if (ev.clientY < r.top + r.height / 2) { list.insertBefore(dragging, rows[i]); return; }
      }
      list.appendChild(dragging);
    });
    ["pointerup", "pointercancel"].forEach(function (evt) {
      list.addEventListener(evt, function () {
        if (!dragging) return;
        dragging.classList.remove("dragging");
        dragging = null;
        // 按 DOM 顺序重排播放单
        var newList = [].slice.call(list.querySelectorAll("li")).map(function (li) {
          return bgm.list[parseInt(li.getAttribute("data-i"), 10)];
        }).filter(Boolean);
        if (newList.length === bgm.list.length) { bgm.list = newList; bgm.userReordered = true; saveBgmList(); renderBgmList(); }
      });
    });
  }

  function paintBgmActive() {
    var ul = document.getElementById("bgm-list");
    if (!ul) return;
    var cur = bgmCurrent();
    [].slice.call(ul.querySelectorAll("li")).forEach(function (li) {
      var i = parseInt(li.getAttribute("data-i"), 10);
      li.classList.toggle("on", !!cur && bgm.list[i] && bgm.list[i].song === cur.song);
    });
    var name = document.getElementById("bgm-now");
    if (name && cur) name.textContent = cur.t;
    paintBgmBar();
  }

  function paintBgmBar() {
    var a = bgm.audio;
    var fill = document.getElementById("bgm-fill");
    var knob = document.getElementById("bgm-knob");
    var tg = document.getElementById("bgm-toggle");
    var md = document.getElementById("bgm-mode");
    if (md) {
      md.textContent = t("bgm." + bgm.mode);
      md.title = t("bgm.mode") + "：" + t("bgm." + bgm.mode);
    }
    if (tg) tg.innerHTML = a && !a.paused ? "❚❚" : "▶";
    if (!a || !fill) return;
    var d = a.duration || 0;
    var r = d ? (a.currentTime / d) * 100 : 0;
    fill.style.width = r + "%";
    if (knob) knob.style.left = r + "%";
  }
  function bgmPaintProgress() { paintBgmBar(); }

  function paintBgmBtn() {
    var b = document.getElementById("bgm-btn");
    if (b) {
      b.classList.toggle("off", !bgm.enabled);
    }
    var off = document.getElementById("bgm-off");
    if (off) off.textContent = bgm.enabled ? "⏻" : "⭘";
  }

  // 供播放器弹窗里的“加入 BGM 播放单”调用
  function bgmAdd(song) {
    if (!song) return;
    loadBgmMeta(function () {
      if (bgm.list.some(function (m) { return m.song === song; })) return;
      bgm.list.push(bgmEntry(song));
      saveBgmList();
      renderBgmList();
      if (!bgm.audio) initBgm();
      else { buildBgmQueue(); }
      toast(t("bgm.added"));
    });
  }

  /* ==================== 初始化 ==================== */
  document.addEventListener("DOMContentLoaded", function () {
    try { initBgm(); } catch (e) {}
    bindReveal();
    bindFilters();
    bindViewSwitch();
    bindSort();
    bindLang();
    bindSearch();
    bindRise();
    bindTopbar();
    refreshFeatured();
  });
})();
