"""版本信息统一入口（GUI 标题、关于框、Release 说明都引用这里）。

发布新版本时只需要改：
  1) VERSION / BUILD_DATE
  2) 仓库根目录的 version.json（程序靠它判断有没有新版）

GITHUB_REPO 必须改成你自己的仓库，否则"检查更新"找不到地址。
"""
APP_NAME = "E7Pilot"
VERSION = "1.2.5"
BUILD_DATE = "2026-11-17"

# 改成你的 GitHub 仓库：用户名/仓库名
GITHUB_REPO = "gcw_dWaVd6eU/e7auto"
RELEASE_PAGE = f"https://atomgit.com/{GITHUB_REPO}/releases"
# 赞赏页：项目首页 README 底部（README 里折叠了微信赞赏码）
DONATE_URL = f"https://atomgit.com/{GITHUB_REPO}#支持与赞赏"

# 更新检查地址（按顺序尝试，全部失败就静默跳过，不打扰用户）
UPDATE_URLS = [
    f"https://atomgit.com/api/v5/repos/{GITHUB_REPO}/raw/version.json?ref=main",
    f"https://raw.atomgit.com/{GITHUB_REPO}/raw/main/version.json",
    f"https://gitee.com/{GITHUB_REPO}/raw/main/version.json",
]
