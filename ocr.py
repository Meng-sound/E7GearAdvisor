"""Persistent Windows OCR subprocess. No screenshot or text leaves this computer."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading


def reconstruct_lines(lines):
    """Windows sometimes separates the stat label and its value into different lines.

    Cluster words by their vertical centres, then sort horizontally. Never join
    adjacent stat rows just because the OCR line order happened to differ.
    """
    words = [w for line in lines for w in line.get("words", [])]
    if not words:
        return "\n".join(l.get("text", "") for l in lines)
    rows = []
    for w in sorted(words, key=lambda x: (x["y"] + x["h"] / 2, x["x"])):
        centre = w["y"] + w["h"] / 2
        target = next((r for r in rows if abs(r["cy"] - centre) < min(r["height"], w["h"]) * .5), None)
        if target is None:
            rows.append({"cy": centre, "height": w["h"], "words": [w]})
        else:
            target["words"].append(w)
    return "\n".join(" ".join(w["text"] for w in sorted(r["words"], key=lambda w: w["x"])) for r in rows)


class WindowsOCR:
    def __init__(self):
        executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        self.process = subprocess.Popen(
            [str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
             str(Path(__file__).with_name("ocr_windows.ps1"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.responses = queue.Queue()
        self.errors = []
        self.lock = threading.Lock()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for line in self.process.stdout:
            try:
                self.responses.put(json.loads(line))
            except json.JSONDecodeError:
                self.errors.append(line.strip())
        self.responses.put({"ok": False, "error": "OCR进程退出：" + " ".join(self.errors[-5:])})

    def _read_stderr(self):
        for line in self.process.stderr:
            self.errors.append(line.strip())

    def request(self, **request):
        with self.lock:
            if self.process.poll() is not None:
                raise RuntimeError("OCR进程不可用：" + " ".join(self.errors[-5:]))
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            try:
                result = self.responses.get(timeout=70)
            except queue.Empty:
                self.close()
                raise RuntimeError("OCR超时，请重启识别后再试") from None
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "OCR失败"))
            if "lines" in result:
                result["text"] = reconstruct_lines(result["lines"])
            return result

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
