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
    if (p.copy) foot = '<button class="pill-link" id="m-copy">' + t("player.copy") + "</button>";
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
    if (!p.embed) {
      mStage.innerHTML = '<div class="loading-note">' + t("player.noEmbed") + "</div>";
      return;
    }
    loadStart();
    var html;
    if (p.kind === "audio") {
      html = '<iframe class="audio-frame" src="' + p.embed + '" allow="autoplay" ' +
             'referrerpolicy="no-referrer" title="' + escapeHtml(p.title) + '" ' +
             'onload="window.__sysLoadEnd()"></iframe>';
    } else {
      html = '<div class="ratio"><iframe src="' + p.embed + '" scrolling="no" border="0" ' +
             'frameborder="no" framespacing="0" allowfullscreen="true" ' +
             'sandbox="allow-scripts allow-same-origin allow-presentation allow-popups" ' +
             'title="' + escapeHtml(p.title) + '" onload="window.__sysLoadEnd()"></iframe></div>';
    }
    mStage.innerHTML = html;
    setTimeout(loadEnd, 1800);
    var copyBtn = document.getElementById("m-copy");
    if (copyBtn && p.source) {
      copyBtn.addEventListener("click", function () {
        navigator.clipboard.writeText(p.source).then(function () {
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
      source: el.getAttribute("data-source") || "",
      sourceLabel: el.getAttribute("data-source-label") || "",
      platform: el.getAttribute("data-platform") || "",
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
      btn.textContent = left <= 0 ? t("section.allShown") : t("section.more");
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
