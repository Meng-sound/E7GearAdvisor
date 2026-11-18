"""E7Pilot · 统一启动菜单（Python 实现，避免 cmd 的中文编码问题）。

用法：
    双击 启动.bat                -> 打开本菜单
    启动.bat 4                   -> 直接启动「秘密商店」
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

MODES: dict[str, tuple[str, list[str]]] = {
    "2": ("原版推图（系统 AUTO 挂机）", ["main.py", "--auto"]),
    "3": ("手操烧魂（手动精控）", ["main.py", "--brieg"]),
    "4": ("秘密商店（刷圣约书签/神秘奖牌）", ["main.py", "--shop"]),
    "5": ("商店 + 推图串联", ["main.py", "--chain"]),
    "6": ("月光剧场自动观影", ["main.py", "--theater"]),
    "7": ("采集界面截图（probe）", ["probe.py", "--loop", "3"]),
    "8": ("测试后台点击是否可用", ["test_bg_click.py"]),
}


def run(args: list[str]) -> int:
    return subprocess.call([PY, *args], cwd=str(ROOT))


def launch_gui() -> None:
    exe = ROOT / "dist" / "E7Pilot" / "E7Pilot.exe"
    if exe.exists():
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
        print("已启动图形界面（E7Pilot.exe）")
    else:
        run(["app.py"])


def fix_permissions() -> None:
    print("\n正在把本文件夹的完整性标签提升为 High（需要管理员权限）…")
    rc = subprocess.call(["icacls", str(ROOT), "/setintegritylevel", "(OI)(CI)H"])
    if rc == 0:
        print("[成功] 已修复。以后若又被打了 Low 标签，重跑本项即可。")
    else:
        print("[失败] 请关掉本窗口，右键 启动.bat -> 以管理员身份运行，再选 9。")


def show_menu() -> str:
    print()
    print("=" * 58)
    print("            E7Pilot   启动菜单")
    print("=" * 58)
    print("  [1] 图形界面（推荐，包含下面全部功能）")
    print()
    print("  [2] 原版推图        [3] 手操烧魂")
    print("  [4] 秘密商店        [5] 商店+推图串联")
    print("  [6] 月光剧场")
    print()
    print("  [7] 采集界面截图     [8] 测试后台点击可行性")
    print("  [9] 修复文件权限（需管理员）")
    print("  [0] 退出")
    print("=" * 58)
    return input("请输入数字后回车（直接回车 = 1 图形界面）：").strip() or "1"


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in MODES:
        return run(MODES[sys.argv[1]][1])

    while True:
        try:
            choice = show_menu()
        except (EOFError, KeyboardInterrupt):
            return 0

        if choice == "0":
            return 0
        if choice == "1":
            launch_gui()
            return 0
        if choice == "9":
            fix_permissions()
            continue
        if choice in MODES:
            return run(MODES[choice][1])
        print(f"无效选择：{choice}")


if __name__ == "__main__":
    sys.exit(main())
