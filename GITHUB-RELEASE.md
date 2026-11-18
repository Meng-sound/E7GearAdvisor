# GitHub 发布步骤

仓库：https://github.com/Meng-sound/E7GearAdvisor

1. 将 `GitHub-Source` 目录内的文件上传到仓库根目录；开启隐藏文件显示以包含 `.github` 和 `.gitignore`。不要上传整个开发目录或个人 userdata。
2. 运行测试。更改 `app_version.py` 的 VERSION 和 RELEASE_DATE 后，用 `tools/build_release.py` 构建到新目录。
3. 打开仓库 Releases → Draft a new release，标签使用 `v1.0.0`，标题 `v1.0.0`。更新器默认只看公开正式版，请勿勾选 Pre-release（测试版可勾选，但不会推送）。
4. 将生成的 `E7GearAdvisor-Windows.zip`、`E7GearAdvisor-Source.zip` 和 `SHA256SUMS.txt` 作为 Release 附件上传；不要单独上传启动器 EXE 当作安装包。
5. 复制 `RELEASE-NOTES.md` 为发布说明，核对后发布。构建目录中的 `BUILD-REPORT.json` 可用于核对离线资源。

更新器默认仓库已设为 `Meng-sound/E7GearAdvisor`。只提交源码而未创建 Release 时，程序会提示尚无公开正式版本。用户手动保存过的仓库配置优先于默认值，可在更新窗口改回本仓库。

Windows ZIP 不进入 Git 源码历史，使用 Release 附件发布。SHA256SUMS.txt 的文件名和哈希必须与本次附件一致；重新打包后重新生成，不能沿用旧哈希。

项目自有代码的统一许可证尚需维护者确定。第三方许可证和署名不得省略；详见 LICENSES.md。
