/* 从 SYSite 的 app.js 里抽出真实的 bringToFront 函数 + pointerdown 补丁，
   在 jsdom 里复现「播放器开着 → 点分享按钮 → 打开分享窗」的全过程，
   断言分享窗的 z-index 高于播放器弹窗。 */
const fs = require("fs");
const { JSDOM } = require(require("path").join(
  "C:/Users/29736/.workbuddy/binaries/node/workspace", "node_modules", "jsdom"));

const src = fs.readFileSync(
  "C:/Users/29736/WorkBuddy/2026-09-18-18-14-59/SYSite/src/scripts/app.js", "utf8");

// 1) 抽出真实的 bringToFront 定义（var zTop 起始行到函数结束）
const m = src.match(/  var zTop = 300;\r?\n  function bringToFront\(node\) \{[\s\S]*?\r?\n  \}/);
if (!m) { console.error("FAIL: 没找到 bringToFront 定义"); process.exit(1); }
const bringCode = m[0];

// 2) 抽出真实的 pointerdown 补丁 IIFE（SEL 那段）
const p = src.match(/  \(function \(\) \{\r?\n    var SEL = [^\r\n]+\r?\n[\s\S]*?\r?\n  \}\)\(\);/);
if (!p) { console.error("FAIL: 没找到 pointerdown 补丁"); process.exit(1); }
const patchCode = p[0];

// ---- jsdom 环境 ----
const dom = new JSDOM(`<!DOCTYPE html><body>
  <div id="modal" class="modal-mask open" style="position:fixed;z-index:200">
    <div class="op-bubble"><button id="share-btn">分享</button></div>
  </div>
  <div id="share-modal" style="position:fixed;z-index:260"></div>
  <div id="bgm-panel" style="position:fixed;z-index:190"></div>
  <button id="bgm-btn">BGM</button>
</body>`, { runScripts: "outside-only" });
const { window } = dom;
const { document } = window;

// 装入真实代码
window.eval(bringCode);
window.eval(patchCode);

const modal = document.getElementById("modal");
const shareModal = document.getElementById("share-modal");
const bgmPanel = document.getElementById("bgm-panel");
const zi = (el) => window.getComputedStyle(el).zIndex;

const results = [];
const assert = (name, cond) => results.push([cond ? "PASS" : "FAIL", name]);

// 场景：播放器开着（z 200），用户点击视频卡操作气泡里的分享按钮
document.getElementById("share-btn").dispatchEvent(
  new window.MouseEvent("pointerdown", { bubbles: true, cancelable: true }));
// 真实行为：op-bubble 在 SEL 里，它的定位祖先是 #modal → 播放器被顶到 301
assert("点分享按钮后播放器被置顶（z=301）", zi(modal) === "301");

// showShareModal 打开时调用 bringToFront(shareModal)
window.eval("bringToFront(document.getElementById('share-modal'));");
assert("分享窗 z 高于播放器（不被遮挡）", parseInt(zi(shareModal)) > parseInt(zi(modal)));

// BGM 面板打开时同样置顶
window.eval("bringToFront(document.getElementById('bgm-panel'));");
assert("BGM 面板 z 高于播放器", parseInt(zi(bgmPanel)) > parseInt(zi(modal)));

// 之后用户再点播放器本身 → 播放器重新置顶（原有交互不回归）
modal.querySelector(".op-bubble").dispatchEvent(
  new window.MouseEvent("pointerdown", { bubbles: true, cancelable: true }));
assert("再点播放器仍能重新置顶（原有交互保留）", parseInt(zi(modal)) > parseInt(zi(shareModal)));

let fail = 0;
for (const [s, name] of results) { console.log(s, "-", name); if (s === "FAIL") fail++; }
process.exit(fail ? 1 : 0);
