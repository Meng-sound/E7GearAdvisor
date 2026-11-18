"""新版本检测。

只读取仓库里公开的 version.json，不上传任何数据、不写注册表、不改游戏。

version.json 格式（放在仓库根目录）：
    {
      "version": "1.1.0",
      "download": "https://github.com/you/repo/releases/latest",
      "notes": "本次更新内容……"
    }
"""
from __future__ import annotations

import json
import re
import urllib.request

from version import RELEASE_PAGE, UPDATE_URLS, VERSION

USER_AGENT = f"E7Pilot/{VERSION} (+update-check)"


def _parse(ver: str) -> tuple[int, int, int]:
    nums = re.findall(r"\d+", str(ver))
    nums = (nums + ["0", "0", "0"])[:3]
    return int(nums[0]), int(nums[1]), int(nums[2])


def _fetch(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    # 容错：部分 CDN/WAF 会在 JSON 前加少量前缀字符，从第一个 { 开始解析
    idx = text.find("{")
    return json.loads(text[idx:] if idx >= 0 else text)


def pick_download_url(urls: list[str], timeout: float = 2.5) -> str:
    """按顺序探测下载源，返回第一个可用的；都不可用则返回第一个（让浏览器自己处理）。"""
    for u in urls:
        try:
            req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if 200 <= resp.status < 400:
                    return u
        except Exception:  # noqa: BLE001
            continue
    return urls[0] if urls else RELEASE_PAGE


def check_update(urls: list[str] | None = None, timeout: float = 4.0) -> dict | None:
    """有新版本时返回 {version, download, notes}，否则返回 None（网络失败也算 None）。"""
    for url in urls or UPDATE_URLS:
        if not url:
            continue
        try:
            data = _fetch(url, timeout)
        except Exception:  # noqa: BLE001
            continue
        latest = str(data.get("version", "")).strip()
        if not latest:
            continue
        try:
            newer = _parse(latest) > _parse(VERSION)
        except Exception:  # noqa: BLE001
            continue
        if newer:
            urls: list[str] = []
            raw_list = data.get("download_urls")
            if isinstance(raw_list, list):
                urls = [str(x) for x in raw_list if x]
            single = data.get("download")
            if single:
                urls.append(str(single))
            if not urls:
                urls = [RELEASE_PAGE]
            return {
                "version": latest,
                "download": urls[0],
                "downloads": urls,
                "notes": str(data.get("notes") or ""),
            }
        return None
    return None
