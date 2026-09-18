/* 雪萤小驿 · 交互脚本
   1) 卡片点击 → 气泡弹窗内在线播放（视频走 B 站播放器，音频走网易云播放器）
   2) 弹窗外链按钮 → 跳转原平台
   3) 语言切换（预留 简/繁/英/日）
   4) 进场动画 / 顶栏吸顶 / 轻提示
*/
(function () {
  "use strict";

  var I18N = window.SYS_I18N || {};
  var t = function (k) {
    var cur = I18N[window.SYS_LOCALE || "zh-CN"] || I18N["zh-CN"] || {};
    var base = I18N["zh-CN"] || {};
    return cur[k] || base[k] || k;
  };

  /* ---------------- 轻提示 ---------------- */
  var toastEl = document.getElementById("toast");
  var toastTimer = null;
  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, 2400);
  }

  /* ---------------- 顶部进度条 ---------------- */
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

  /* ---------------- 播放弹窗 ---------------- */
  var mask = document.getElementById("modal");
  var modal = mask ? mask.querySelector(".modal") : null;
  var mTitle = document.getElementById("m-title");
  var mMeta = document.getElementById("m-meta");
  var mStage = document.getElementById("m-stage");
  var mFoot = document.getElementById("m-foot");
  var lastFocus = null;

  function openModal(payload) {
    if (!mask) return;
    lastFocus = document.activeElement;
    mTitle.textContent = payload.title || "";
    mMeta.textContent = payload.meta || "";
    mStage.innerHTML = '<div class="loading-note">' + t("player.loading") + "</div>";

    var foot = "";
    if (payload.source) {
      foot += '<a class="pill-link primary" href="' + payload.source + '" target="_blank" rel="noopener noreferrer">' +
              (payload.sourceLabel || t("player.openSource")) +
              ' <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>' +
              "</a>";
    }
    if (payload.platform) {
      foot += '<span class="mnote">' + payload.platform + "</span>";
    }
    if (payload.copy) {
      foot = '<button class="pill-link" id="m-copy">' + t("player.copy") + "</button>" + foot;
    }
    mFoot.innerHTML = foot;

    mask.classList.add("open");
    document.body.style.overflow = "hidden";
    if (modal) modal.scrollTop = 0;

    // 弹窗展开后再挂 iframe，避免播放器在动画中抢焦点
    setTimeout(function () { inject(payload); }, 60);
  }

  function inject(payload) {
    if (!payload.embed) {
      mStage.innerHTML = '<div class="loading-note">' + t("player.noEmbed") + "</div>";
      return;
    }
    loadStart();
    var html;
    if (payload.kind === "audio") {
      html = '<iframe class="audio-frame" src="' + payload.embed + '" allow="autoplay" ' +
             'referrerpolicy="no-referrer" title="' + (payload.title || "") + '" ' +
             'onload="window.__sysLoadEnd()"></iframe>';
    } else {
      html = '<div class="ratio"><iframe src="' + payload.embed + '" scrolling="no" border="0" ' +
             'frameborder="no" framespacing="0" allowfullscreen="true" ' +
             'sandbox="allow-scripts allow-same-origin allow-presentation allow-popups" ' +
             'title="' + (payload.title || "") + '" onload="window.__sysLoadEnd()"></iframe></div>';
    }
    mStage.innerHTML = html;
    setTimeout(loadEnd, 1800);
    var copyBtn = document.getElementById("m-copy");
    if (copyBtn && payload.source) {
      copyBtn.addEventListener("click", function () {
        navigator.clipboard.writeText(payload.source).then(function () {
          toast(t("player.copied"));
        }, function () { toast(t("player.copyFail")); });
      });
    }
  }
  window.__sysLoadEnd = loadEnd;

  function closeModal() {
    if (!mask) return;
    mask.classList.remove("open");
    document.body.style.overflow = "";
    setTimeout(function () {
      mStage.innerHTML = "";   // 卸载 iframe，停止播放
      mFoot.innerHTML = "";
    }, 340);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  if (mask) {
    mask.addEventListener("click", function (e) {
      if (e.target === mask) closeModal();
    });
    var closeBtn = mask.querySelector(".modal-close");
    if (closeBtn) closeBtn.addEventListener("click", closeModal);
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && mask && mask.classList.contains("open")) closeModal();
  });

  /* ---------------- 卡片点击（事件委托，动态插入的内容也能点） ---------------- */
  function payloadOf(el) {
    return {
      title: el.getAttribute("data-title") || "",
      meta: el.getAttribute("data-meta") || "",
      embed: el.getAttribute("data-embed") || "",
      kind: el.getAttribute("data-kind") || "video",
      source: el.getAttribute("data-source") || "",
      sourceLabel: el.getAttribute("data-source-label") || "",
      platform: el.getAttribute("data-platform") || "",
      copy: el.getAttribute("data-copy") === "1"
    };
  }

  function bindPlayables() {
    document.addEventListener("click", function (ev) {
      var el = ev.target.closest ? ev.target.closest("[data-play]") : null;
      if (!el) return;
      if (ev.target.closest("a")) return;   // 卡片内的外链不劫持
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
  }

  /* ---------------- 语言切换 ----------------
     每种语言是一份独立页面，菜单项就是普通链接，直接跳转即可，
     JS 只负责开合菜单与动画。 */
  function bindLang() {
    var btn = document.getElementById("lang-btn");
    var menu = document.getElementById("lang-menu");
    if (!btn || !menu) return;
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      menu.classList.toggle("open");
    });
    menu.addEventListener("click", function (e) { e.stopPropagation(); });
    document.addEventListener("click", function () { menu.classList.remove("open"); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") menu.classList.remove("open");
    });
  }

  /* ---------------- 折叠与「显示更多」 ---------------- */
  var STEP = 12;
  var revealState = new WeakMap();

  function applyLimit(box, show) {
    var kids = [].slice.call(box.children);
    kids.forEach(function (k, idx) {
      if (idx >= show) k.classList.add("is-hidden");
      else k.classList.remove("is-hidden");
    });
  }

  function bindReveal() {
    var boxes = document.querySelectorAll("[data-reveal]");
    for (var i = 0; i < boxes.length; i++) {
      (function (box) {
        var show = parseInt(box.getAttribute("data-reveal") || "12", 10);
        var kids = [].slice.call(box.children);
        if (kids.length <= show) return;
        revealState.set(box, { show: show, step: STEP });
        applyLimit(box, show);

        var holder = box.nextElementSibling;
        var btn = holder ? holder.querySelector("[data-more-btn]") : null;
        if (!btn) return;
        btn.setAttribute("data-step", String(STEP));
        btn.addEventListener("click", function () {
          var st = revealState.get(box) || { show: show, step: STEP };
          st.show = st.show + st.step;
          revealState.set(box, st);
          var hidden = [].slice.call(box.children).filter(function (k) {
            return k.classList.contains("is-hidden");
          });
          hidden.slice(0, st.step).forEach(function (k, idx) {
            k.classList.remove("is-hidden");
            k.classList.remove("rise");
            k.classList.add("revealed");
            k.style.animationDelay = (idx * 28) + "ms";
            if (!k.classList.contains("in")) k.classList.add("in");
          });
          var left = [].slice.call(box.children).filter(function (k) {
            return k.classList.contains("is-hidden");
          }).length;
          if (left === 0) {
            btn.classList.add("more-done");
            btn.disabled = true;
            btn.textContent = t("section.allShown");
          } else {
            btn.classList.remove("more-done");
            btn.disabled = false;
            btn.textContent = t("section.more");
          }
        });
      })(boxes[i]);
    }
  }

  /* ---------------- 精选栏：跟随排序实时同步 ----------------
     精选栏不是写死的，它跟着「视频投稿 / 音乐」两个区块当前的排序结果走，
     默认取前 N 名（N 由构建期的 featured.maxItems 决定，默认 20）。
     用户切换排序依据或翻转正倒序时，精选也会跟着变。
     来自独立合集的榜单（精选吴语视频）不带 data-top3，保持静态。 */
  function miniFromCard(card, rank) {
    var img = card.querySelector(".card-cover img");
    var kind = card.getAttribute("data-kind") || "video";
    var title = card.getAttribute("data-title") || "";
    var meta = card.getAttribute("data-meta") || "";
    var square = kind === "audio" ? " sq" : "";
    var thumb = img ? '<span class="mini-thumb' + square + '"><img src="' + img.getAttribute("src") +
                      '" alt="" loading="lazy" decoding="async"></span>' : "";
    var rankCls = rank === 1 ? "" : (rank === 2 ? " r2" : " r3");
    function q(s) { return String(s).replace(/"/g, "&quot;"); }
    function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
    return '<button class="mini" type="button" data-play="1" data-kind="' + kind + '"' +
           ' data-title="' + q(title) + '"' +
           ' data-meta="' + q(meta) + '"' +
           ' data-embed="' + q(card.getAttribute("data-embed") || "") + '"' +
           ' data-source="' + q(card.getAttribute("data-source") || "") + '"' +
           ' data-source-label="' + q(card.getAttribute("data-source-label") || "") + '"' +
           ' data-platform="' + q(card.getAttribute("data-platform") || "") + '">' +
           thumb +
           '<span class="mini-body"><span class="mini-title"><span class="mini-rank' + rankCls + '">' +
           rank + "</span>" + esc(title) + "</span>" +
           '<span class="mini-meta">' + esc(meta) + "</span></span></button>";
  }

  function refreshTop3() {
    var holders = document.querySelectorAll("[data-top3]");
    for (var i = 0; i < holders.length; i++) {
      var holder = holders[i];
      var key = holder.getAttribute("data-top3");
      var limit = parseInt(holder.getAttribute("data-top3-limit") || "20", 10);
      var grid = document.querySelector('[data-sortable="' + key + '"]');
      if (!grid) continue;
      var kids = [].slice.call(grid.children).slice(0, limit);
      var html = "";
      for (var j = 0; j < kids.length; j++) html += miniFromCard(kids[j], j + 1);
      holder.innerHTML = html;
      holder.classList.remove("revealed");
      void holder.offsetWidth;
      holder.classList.add("revealed");
    }
  }

  /* ---------------- 排序：时间 / 热度，正序 / 倒序 ---------------- */
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
          var mode = bar.getAttribute("data-mode") || "time";
          var dir = bar.getAttribute("data-dir") || "desc";
          var attr = mode === "heat" ? "data-heat" : "data-ts";
          var kids = [].slice.call(grid.children);
          kids.sort(function (a, b) {
            var av = parseFloat(a.getAttribute(attr) || "0") || 0;
            var bv = parseFloat(b.getAttribute(attr) || "0") || 0;
            if (av === bv) {
              // 同值时用投稿时间兜底，保证顺序稳定
              var at = parseFloat(a.getAttribute("data-ts") || "0") || 0;
              var bt = parseFloat(b.getAttribute("data-ts") || "0") || 0;
              return dir === "desc" ? bt - at : at - bt;
            }
            return dir === "desc" ? bv - av : av - bv;
          });
          kids.forEach(function (k) {
            k.classList.remove("revealed");
            grid.appendChild(k);
          });

          // 重排后重新折叠，避免一次露出全部
          var st = revealState.get(grid);
          if (st) {
            applyLimit(grid, st.show);
            var holder = grid.nextElementSibling;
            var btn = holder ? holder.querySelector("[data-more-btn]") : null;
            if (btn) {
              var left = [].slice.call(grid.children).filter(function (k) {
                return k.classList.contains("is-hidden");
              }).length;
              btn.disabled = left === 0;
              btn.classList.toggle("more-done", left === 0);
              btn.textContent = left === 0 ? t("section.allShown") : t("section.more");
            }
          }

          grid.classList.remove("is-sorting");
          void grid.offsetWidth;
          grid.classList.add("is-sorting");
          setTimeout(function () { grid.classList.remove("is-sorting"); }, 420);
          refreshTop3();   // 精选前三跟随排序
        }

        for (var j = 0; j < modeBtns.length; j++) {
          if (modeBtns[j].getAttribute("data-set-mode") === (bar.getAttribute("data-mode") || "time")) {
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

  /* ---------------- 进场动画 ---------------- */
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
          var delay = parseInt(el.getAttribute("data-delay") || "0", 10);
          setTimeout(function () { el.classList.add("in"); }, delay);
          io.unobserve(el);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.06 });
    for (var j = 0; j < els.length; j++) io.observe(els[j]);
  }

  /* ---------------- 顶栏吸顶 ---------------- */
  function bindTopbar() {
    var bar = document.querySelector(".topbar");
    if (!bar) return;
    var onScroll = function () {
      if (window.scrollY > 8) bar.classList.add("is-stuck");
      else bar.classList.remove("is-stuck");
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* ---------------- 站内搜索 ----------------
     索引在构建期生成（assets/search-index.<lang>.json），
     运行时只做本地过滤，不发任何请求到第三方。 */
  function bindSearch() {
    var page = document.getElementById("search-page");
    if (!page) return;
    var input = document.getElementById("q");
    var results = document.getElementById("search-results");
    var note = document.getElementById("search-note");
    var idxUrl = page.getAttribute("data-index");
    var state = { q: "", type: "", year: "" };
    var data = null;
    var LIMIT = 60;

    function esc(s) {
      return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }
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
          '<img src="' + esc(it.c) + '" alt="" loading="lazy" decoding="async">' +
          (it.k === "audio" && it.x ? '<span class="badge">' + esc(it.x) + "</span>" : "") + "</div>"
        : "";
      if (it.e) {
        return '<article class="card search-hit" data-play="1" data-kind="' +
          (it.k === "audio" ? "audio" : "video") + '" tabindex="0" role="button"' +
          ' data-title="' + esc(it.t) + '" data-meta="' + meta + '"' +
          ' data-embed="' + esc(it.e) + '" data-source="' + esc(it.u) + '"' +
          ' data-source-label="' + esc(it.l) + '" data-platform="' + esc(it.pl) + '">' +
          cover + '<div class="card-body"><h3 class="card-title">' + title + "</h3>" +
          '<div class="card-meta"><span>' + meta + "</span></div></div></article>";
      }
      if (it.k === "project") {
        return '<a class="card repo-card search-hit" href="' + esc(it.u) +
          '" target="_blank" rel="noopener noreferrer">' +
          '<div class="rname">' + title + "</div>" +
          '<div class="rdesc">' + esc(it.d || "") + "</div>" +
          '<div class="rmeta"><span>' + meta + "</span></div></a>";
      }
      return '<a class="post search-hit" href="' + esc(it.u) +
        '" target="_blank" rel="noopener noreferrer">' +
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
        if (ql && it.s.indexOf(ql) === -1) return false;
        return true;
      });
      var shown = hit.slice(0, LIMIT);
      results.className = hit.length && hit[0].k === "post" ? "posts" : "grid videos";
      results.innerHTML = shown.map(function (it) { return cardHtml(it, q); }).join("");
      note.textContent = q || state.type || state.year
        ? t("search.count").replace("{n}", hit.length)
        : t("search.hint");
      if (!hit.length && (q || state.type || state.year)) {
        results.innerHTML = '<div class="pin-empty">' + t("search.empty") + "</div>";
        results.className = "";
      }
    }

    input.addEventListener("input", function () {
      state.q = input.value;
      render();
    });
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

    fetch(idxUrl).then(function (r) { return r.json(); }).then(function (j) {
      data = j;
      render();
    }).catch(function () {
      note.textContent = t("search.failed");
    });

    // 支持 ?q= 直达
    var pre = new URLSearchParams(location.search).get("q");
    if (pre) { input.value = pre; state.q = pre; }
  }

  /* ---------------- 初始化 ---------------- */
  document.addEventListener("DOMContentLoaded", function () {
    bindPlayables();
    bindReveal();
    bindSort();
    bindLang();
    bindSearch();
    refreshTop3();
    bindRise();
    bindTopbar();
    var brand = document.querySelector(".brand");
    if (brand) {
      brand.addEventListener("click", function (e) {
        e.preventDefault();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    }
  });
})();
