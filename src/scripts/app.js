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

  function openModal(p) {
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
      // 直链和歌词是构建期取的，首次点击时才按需拉取
      loadAudioData().then(function () {
        var d = AUDIO[p.song];
        if (d && d.u) renderAudio(p);
        else renderVideoOrEmbed(p);   // 没有直链 → 用官方播放器兜底
      });
      return;
    }
    renderVideoOrEmbed(p);
  }

  /* ---------------- 自有音频播放器 ----------------
     用原生 <audio> + 我们自己画的界面：海报、动态歌词、进度、上一首下一首。
     数据（音频直链 + LRC 歌词）是构建期取好放在 assets/player-data.json 里的。
     取不到直链、或播放中途报错 → 自动回落官方播放器，并在底部说明。 */
  var PLAYER_CFG = window.SYS_PLAYER || {};
  var AUDIO = {};             // songId -> {u,b,l,t}
  var audioReady = null;
  var pl = null;              // 当前播放列表
  var plIdx = -1;
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
      '<div class="op" id="op">' +
      '  <div class="op-bg" id="op-bg"></div><div class="op-scrim"></div>' +
      '  <div class="op-inner">' +
      '    <div class="op-left">' +
      '      <div class="op-art"><img id="op-art" alt=""></div>' +
      '      <div><h4 class="op-title" id="op-title"></h4><p class="op-sub" id="op-sub"></p></div>' +
      "    </div>" +
      '    <div class="op-right">' +
      '      <div class="op-lyhead">' +
      '        <span class="op-lylabel">' + esc(t("player.lyrics")) + "</span>" +
      '        <button class="op-tr-toggle" id="op-tr" type="button" aria-pressed="true">' +
      "          <span>" + esc(t("player.translation")) + "</span>" +
      '          <span class="op-check"><svg viewBox="0 0 24 24" aria-hidden="true">' +
      '<path d="M20 6L9 17l-5-5"/></svg></span>' +
      "        </button>" +
      "      </div>" +
      '      <div class="op-lyrics" id="op-lyrics"></div>' +
      "    </div>" +
      "  </div>" +
      '  <div class="op-inner" style="padding-top:0">' +
      '    <div class="op-bar" style="grid-column:1/-1">' +
      '      <button class="op-btn" id="op-prev" type="button" aria-label="prev">' + icon("prev") + "</button>" +
      '      <button class="op-btn main" id="op-toggle" type="button" aria-label="play">' + icon("play") + "</button>" +
      '      <button class="op-btn" id="op-next" type="button" aria-label="next">' + icon("next") + "</button>" +
      '      <span class="op-time" id="op-cur">0:00</span>' +
      '      <span class="op-seek" id="op-seek"><span class="op-track"><span class="op-fill" id="op-fill"></span></span><span class="op-knob" id="op-knob"></span></span>' +
      '      <span class="op-time" id="op-dur">0:00</span>' +
      '      <button class="op-btn" id="op-vol" type="button" aria-label="mute">' + icon("volume") + "</button>" +
      '      <span class="op-seek op-vol" id="op-volbar"><span class="op-track"><span class="op-fill" id="op-volfill"></span></span><span class="op-knob" id="op-volknob"></span></span>' +
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
    a.addEventListener("error", function () { fallbackToOfficial(t("player.streamFail")); });

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
      var r = ratioOf(ev);
      onRatio(r);
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
    var a = el.audio;
    var d = a.duration || 0;
    var r = d ? (a.currentTime / d) * 100 : 0;
    el.fill.style.width = r + "%";
    el.knob.style.left = r + "%";
    el.cur.textContent = fmtTime(a.currentTime);
    if (d && el.dur.textContent === "0:00") el.dur.textContent = fmtTime(d);
  }

  function load(item) {
    var d = AUDIO[item.song] || {};
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
      el.lyrics.innerHTML = '<p class="op-empty">' + esc(d.u ? t("player.noLyric") : t("player.notPlayable")) + "</p>";
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

    // 音源
    if (d.u) {
      el.audio.src = d.u;
      el.audio.load();
      el.root.classList.remove("op-failed");
      removeFallbackNote();
    } else {
      fallbackToOfficial(t("player.notPlayable"));
    }
    paintVol();
    mFoot.innerHTML = buildFoot(item);
  }

  function buildFoot(item) {
    var s = "";
    if (item.source) {
      s += '<a class="pill-link primary" href="' + attr(item.source) + '" target="_blank" rel="noopener noreferrer">' +
           (item.label || t("player.openSource")) +
           ' <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg></a>';
    }
    if (item.platform) s += '<span class="mnote">' + esc(item.platform) + "</span>";
    return s;
  }

  function nextTrack(step) {
    if (!pl || pl.length < 2) return;
    plIdx = (plIdx + step + pl.length) % pl.length;
    lastLrcIdx = -1;
    load(pl[plIdx]);
    el.audio.play().catch(function () {});
  }

  function syncLyrics() {
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
  function fallbackToOfficial(note) {
    if (!el.root) return;
    el.root.classList.add("op-failed");
    try { el.audio.pause(); } catch (e) {}
    removeFallbackNote();
    var host = mStage.querySelector("#op");
    if (!host) return;
    var box = document.createElement("div");
    box.className = "op-fallback-note";
    box.textContent = note;
    host.appendChild(box);
  }

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
    if (!mask) return;
    mask.classList.remove("open");
    document.body.style.overflow = "";
    // 关闭即彻底停掉音频，避免后台继续播放
    if (el && el.audio) {
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

  /* ==================== 初始化 ==================== */
  document.addEventListener("DOMContentLoaded", function () {
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
