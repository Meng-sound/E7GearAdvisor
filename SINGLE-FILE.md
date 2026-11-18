# 单文件 Windows 版本

下载 E7GearAdvisor.exe 后双击运行。它内置原 Windows 完整包，包括离线 OCR、393 名英雄参考、头像、神器、套装图标、后台任务及所有随包许可。

首次运行自动校验并展开到 `%LOCALAPPDATA%/E7GearAdvisor/versions/`。后续启动直接复用相同版本的缓存，不反复解压，也不需要 EXE 旁边附带任何文件。

个人设置独立保存在 `%LOCALAPPDATA%/E7GearAdvisor/userdata/`，与版本缓存分离。升级时下载新 EXE 即可。旧 ZIP 用户如需保留设置，关闭程序后将旧 `userdata` 里的内容复制到这里。请勿复制维护者的测试数据。

支持 Windows x64，依赖 .NET Framework 4.7.2 或更高版本。EXE 没有改变游戏取图和后台输入的兼容限制，游戏仍不能最小化。

## GitHub 发布

Release 附件只上传 **E7GearAdvisor.exe** 即可。保留文件名，供更新器识别。可删除原 Windows ZIP 附件，避免旧版更新器优先选择 ZIP。GitHub 提供附件 digest 时更新器可直接读取；缺少 digest 时仍需提供 SHA256SUMS.txt。

本机验证包位于 release-single-v1.0.0-verified；不要将其 verify-cache 或生成的中间文件发布为附件。

## 维护者构建

先按 tools/build_release.py 生成干净的 Windows ZIP，然后在 Windows 上执行：

```powershell
python tools/build_single_file.py --payload C:/path/to/E7GearAdvisor-Windows.zip --output C:/path/to/new-release/E7GearAdvisor.exe
```

脚本调用 Windows .NET Framework C# 编译器，将完整 ZIP 作为资源嵌入，不依赖外部压缩工具。支持缓存准备的无界面检查 `E7GearAdvisor.exe --prepare-only`；它不会启动游戏或自动任务。

本单文件方案是自动展开运行环境，并非把 Python 和数据转换成无需磁盘文件的本机代码。实际运行文件会占用本机缓存空间，所有第三方版权及许可证均保留。
