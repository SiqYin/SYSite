"""一键构建：采集 → 封面 → 渲染 → 字体子集。

顺序不能乱：
  collect 产出统一模型的快照 →
  assets 把封面落地为本地 WebP →
  site   把快照渲染成静态页 →
  font   扫描渲染结果，切出只含实际用字的字体子集
"""

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STEPS = [
    ("采集数据", ["collect_all.py"]),
    ("处理封面", ["build_assets.py"]),
    ("生成分享卡片", ["build_og.py"]),
    ("渲染站点", ["build_site.py"]),
    ("字体子集", ["build_font.py"]),
]


def find_python():
    """优先用带 pillow/fonttools 的虚拟环境解释器。"""
    for cand in (os.path.expanduser(r"~\.workbuddy\binaries\python\envs\default\Scripts\python.exe"),
                 r"C:\Users\29736\.workbuddy\binaries\python\envs\default\Scripts\python.exe"):
        if os.path.exists(cand):
            return cand
    return sys.executable


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-collect", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    py = find_python()
    print("解释器：%s" % py)
    steps = STEPS[1:] if args.skip_collect else STEPS
    t0 = time.time()
    for label, argv in steps:
        print("\n" + "#" * 60)
        print("# %s" % label)
        print("#" * 60)
        cmd = [py, os.path.join(HERE, argv[0])] + (["--only", args.only] if args.only and argv[0] == "collect_all.py" else [])
        rc = subprocess.call(cmd, cwd=ROOT)
        if rc != 0:
            print("\n! 步骤「%s」失败（退出码 %s），已中止" % (label, rc))
            return rc
    print("\n全部完成，总用时 %.1fs" % (time.time() - t0))
    print("产物目录：%s" % os.path.join(ROOT, "dist"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
