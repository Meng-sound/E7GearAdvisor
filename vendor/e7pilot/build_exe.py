"""E7Pilot —— 打包脚本。

默认 PyInstaller（快，Py 字节码可被拆包，适合快速分发）；
可选用 Nuitka 编译（C 级产物，逆向门槛更高，需 MSVC/MinGW 与较长编译时间）。

用法：
    python build_exe.py                 # PyInstaller onedir（推荐日常）
    python build_exe.py --onefile       # PyInstaller 单文件
    python build_exe.py --nuitka        # Nuitka 编译（反逆向更强，慢）
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "E7Pilot"


def build_pyinstaller(onefile: bool) -> int:
    import PyInstaller.__main__ as pyi

    # ==================== 质量闸门（不通过就不打包） ====================
    import py_compile as _pyc

    _py_files = [f for f in ROOT.glob("*.py")]
    _bad = []
    for _f in _py_files:
        try:
            _pyc.compile(str(_f), doraise=True)
        except Exception as exc:  # noqa: BLE001
            _bad.append(f"{_f.name}: {exc}")
    if _bad:
        print("[闸门] 语法错误，已终止打包：")
        for b in _bad:
            print("   ", b)
        raise SystemExit(1)

    try:
        import subprocess as _sp

        _r = _sp.run(
            [sys.executable, "dev/check_missing_methods.py"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )
        if _r.returncode != 0:
            print("[闸门] 存在「调用了但未定义的方法」，已终止打包：")
            print(_r.stdout.strip()[:800])
            raise SystemExit(1)
    except FileNotFoundError:
        pass

    print("[闸门] 语法 + 方法检查通过")

    dist = ROOT / "dist"
    # 先把 dist 里的运行数据（统计/日志/样本）备份出来，打包完成后还原
    backup = ROOT / ".dist_debug_backup"
    old_debug = dist / f"{NAME}" / "debug" if False else None
    try:
        cand = dist / "E7Pilot" / "debug"
        if cand.exists():
            shutil.rmtree(backup, ignore_errors=True)
            shutil.copytree(cand, backup)
    except Exception:  # noqa: BLE001
        pass
    if dist.exists():
        shutil.rmtree(dist, ignore_errors=True)
    (ROOT / "build").mkdir(exist_ok=True)

    args = [
        str(ROOT / "app.py"),
        "--noconfirm", "--clean",
        "--name", NAME,
        "--windowed",
        "--uac-admin",
        "--onefile" if onefile else "--onedir",
        "--add-data", f"{ROOT / 'rules.yaml'};.",
        "--add-data", f"{ROOT / 'templates'};templates",
        "--hidden-import", "main",
        "--hidden-import", "shop",
        "--hidden-import", "chain",
        "--hidden-import", "theater",
        "--hidden-import", "combat",
        "--hidden-import", "core",
        "--hidden-import", "probe",
        "--hidden-import", "version",
        "--collect-all", "rapidocr_onnxruntime",
        "--collect-all", "onnxruntime",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pandas",
        "--exclude-module", "torch",
        "--exclude-module", "scipy",
        "--exclude-module", "tkinter.test",
        "--distpath", str(dist),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    pyi.run(args)
    # 清理本项目用不到的大文件（视频后端 / AVIF 支持），显著减小发布包
    try:
        removed_mb = 0.0
        patterns = (
            "_internal/cv2/opencv_videoio_ffmpeg*.dll",
            "_internal/PIL/_avif*.pyd",
        )
        for pat in patterns:
            for f in dist.rglob(pat.split("/")[-1]):
                if f.is_file() and "cv2" in str(f) or f.name.startswith("_avif"):
                    try:
                        removed_mb += f.stat().st_size / 1024 / 1024
                        f.unlink()
                    except Exception:  # noqa: BLE001
                        pass
        if removed_mb:
            print(f"[瘦身] 已移除用不到的文件：{removed_mb:.1f} MB")
    except Exception:  # noqa: BLE001
        pass

    # 附带诊断工具（若存在）
    try:
        _bat = ROOT / "release" / "E7Pilot_诊断修复.bat"
        if _bat.exists():
            shutil.copy2(_bat, dist / "E7Pilot" / "E7Pilot_诊断修复.bat")
            print("[附加] 已放入诊断工具 E7Pilot_诊断修复.bat")
    except Exception:  # noqa: BLE001
        pass

    # 还原 debug 数据
    try:
        if backup.exists():
            target = dist / "E7Pilot" / "debug"
            target.mkdir(parents=True, exist_ok=True)
            for f in backup.iterdir():
                if f.is_file():
                    shutil.copy2(f, target / f.name)
            shutil.rmtree(backup, ignore_errors=True)
            print(f"[数据] 已保留原有 debug 数据：{target}")
    except Exception:  # noqa: BLE001
        pass

    exe = dist / (f"{NAME}.exe" if onefile else f"{NAME}/{NAME}.exe")
    if not exe.exists():
        print("[FAIL] 打包失败：找不到 exe")
        return 1
    print(f"[OK] 打包完成：{exe}（{exe.stat().st_size / 1024 / 1024:.0f} MB 主程序）")
    return 0


def build_nuitka(onefile: bool) -> int:
    """Nuitka：编译成 C 再生成 exe，逆对比 PyInstaller 难一个量级（但非绝对）。"""
    if shutil.which("cl") is None and shutil.which("gcc") is None:
        print("[WARN] 未检测到 MSVC(gcc/cl)，Nuitka 可能无法编译；可安装 Visual Studio Build Tools 后重试。")
    out = ROOT / "dist_nuitka"
    args = [
        sys.executable, "-m", "nuitka",
        "--assume-yes-for-downloads",
        "--windows-disable-console",
        "--windows-uac-admin",
        "--enable-plugin=tk-inter",
        "--include-data-file=rules.yaml=rules.yaml",
        "--include-data-dir=templates=templates",
        "--include-data-dir=assets=assets",
        "--include-package=rapidocr_onnxruntime",
        "--include-package=onnxruntime",
        "--include-module=main",
        "--include-module=shop",
        "--include-module=chain",
        "--include-module=theater",
        "--include-module=combat",
        "--include-module=core",
        "--include-module=probe",
        "--include-module=version",
        "--output-dir", str(out),
        str(ROOT / "app.py"),
    ]
    if onefile:
        args.insert(2, "--onefile")
    print("Nuitka 编译中（可能 10~30 分钟）…")
    return subprocess.call(args, cwd=str(ROOT))


def main() -> int:
    if "--nuitka" in sys.argv:
        return build_nuitka("--onefile" in sys.argv)
    return build_pyinstaller("--onefile" in sys.argv)


if __name__ == "__main__":
    sys.exit(main())
