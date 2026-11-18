using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.7.2")]

internal static class SingleFileLauncher {
    private const string PayloadHash = "__PAYLOAD_SHA256__";
    private const string Version = "__APP_VERSION__";
    private static string Home;
    private static string Cache;

    [STAThread] private static int Main(string[] args) {
        AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
        AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
        Home = Path.GetFullPath(Environment.GetEnvironmentVariable("E7_ADVISOR_LAUNCHER_HOME") ??
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "E7GearAdvisor"));
        Cache = Path.GetFullPath(Path.Combine(Home, "versions", Version + "-" + PayloadHash.Substring(0, 16)));
        // The headless mode exercises exactly the same extraction and validation.
        if (args.Length == 1 && args[0] == "--prepare-only") {
            try { Prepare(delegate(int value) {}); return 0; }
            catch (Exception error) { WriteError(error); return 1; }
        }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        using (var form = new Form()) {
            form.Text = "装备强化计算器"; form.ClientSize = new System.Drawing.Size(420, 125);
            form.StartPosition = FormStartPosition.CenterScreen; form.FormBorderStyle = FormBorderStyle.FixedDialog;
            form.MaximizeBox = false; form.MinimizeBox = false;
            var label = new Label { Left = 22, Top = 20, Width = 380, Height = 42,
                Text = "正在准备运行环境…\n首次运行需要展开文件，请稍候。" };
            var progress = new ProgressBar { Left = 22, Top = 76, Width = 376, Height = 22 };
            form.Controls.Add(label); form.Controls.Add(progress);
            bool preparing = true;
            form.FormClosing += delegate(object sender, FormClosingEventArgs e) { if (preparing) e.Cancel = true; };
            form.Shown += async delegate {
                try {
                    await Task.Run(delegate {
                        Prepare(delegate(int value) {
                            form.BeginInvoke((Action)delegate { progress.Value = Math.Max(0, Math.Min(100, value)); });
                        });
                    });
                    StartApp();
                } catch (Exception error) {
                    WriteError(error);
                    MessageBox.Show("启动未完成：" + error.Message + "\n详情：" + Path.Combine(Home, "launcher-error.log"),
                        "装备强化计算器", MessageBoxButtons.OK, MessageBoxIcon.Error);
                } finally { preparing = false; form.Close(); }
            };
            Application.Run(form);
        }
        return 0;
    }
    private static void WriteError(Exception error) {
        try { Directory.CreateDirectory(Home); File.WriteAllText(Path.Combine(Home, "launcher-error.log"), error.ToString(), Encoding.UTF8); }
        catch { }
    }
    private static Stream Payload() { return Assembly.GetExecutingAssembly().GetManifestResourceStream("E7Payload.zip"); }
    private static bool Ready() {
        string marker = Path.Combine(Cache, ".payload-sha256");
        if (!File.Exists(marker) || File.ReadAllText(marker).Trim() != PayloadHash) return false;
        foreach (string name in new[] { "runtime/pythonw.exe", "runtime/python.exe", "pc_app.py", "pilot_worker.py",
            "data/hero-build-references.json", "vendor/e7pilot/LICENSE" }) {
            if (!File.Exists(Path.Combine(Cache, name))) return false;
        }
        return true;
    }
    private static void Prepare(Action<int> progress) {
        Directory.CreateDirectory(Path.GetDirectoryName(Cache));
        using (var mutex = new Mutex(false, "Local\\E7GearAdvisor-" + PayloadHash.Substring(0, 24))) {
            bool held = false;
            try {
                try { held = mutex.WaitOne(TimeSpan.FromMinutes(5)); }
                catch (AbandonedMutexException) { held = true; }
                if (!held) throw new IOException("另一个启动程序仍在准备文件，请稍后重试。");
                if (Ready()) { progress(100); return; }
                using (var stream = Payload()) using (var sha = SHA256.Create()) {
                    string hash = BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
                    if (hash != PayloadHash) throw new InvalidDataException("安装包校验失败，请重新下载完整 EXE。");
                }
                string staging = Cache + ".staging-" + Guid.NewGuid().ToString("N");
                Directory.CreateDirectory(staging);
                try {
                    using (var stream = Payload()) using (var archive = new ZipArchive(stream, ZipArchiveMode.Read)) {
                        int completed = 0;
                        string prefix = "E7GearAdvisor/";
                        foreach (var entry in archive.Entries) {
                            if (!entry.FullName.StartsWith(prefix, StringComparison.Ordinal)) throw new InvalidDataException("安装包根目录不正确。");
                            string relative = entry.FullName.Substring(prefix.Length);
                            string destination = Path.GetFullPath(Path.Combine(staging, relative));
                            if (!destination.StartsWith(staging + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                                throw new InvalidDataException("安装包包含无效路径。");
                            if (entry.FullName.EndsWith("/")) Directory.CreateDirectory(destination);
                            else {
                                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                                using (var input = entry.Open()) using (var output = new FileStream(destination, FileMode.CreateNew)) input.CopyTo(output);
                                if (new FileInfo(destination).Length != entry.Length) throw new InvalidDataException("文件展开不完整。");
                            }
                            progress(++completed * 100 / archive.Entries.Count);
                        }
                    }
                    File.WriteAllText(Path.Combine(staging, ".payload-sha256"), PayloadHash, Encoding.ASCII);
                    // Only the known immutable cache for this payload may be replaced.
                    if (Directory.Exists(Cache)) {
                        string old = Cache + ".incomplete-" + Guid.NewGuid().ToString("N");
                        Directory.Move(Cache, old);
                    }
                    Directory.Move(staging, Cache);
                    if (!Ready()) throw new InvalidDataException("运行环境文件缺失。");
                } finally {
                    if (Directory.Exists(staging)) Directory.Delete(staging, true);
                }
            } finally { if (held) mutex.ReleaseMutex(); }
        }
    }
    private static void StartApp() {
        string user = Environment.GetEnvironmentVariable("E7_ADVISOR_HOME") ?? Path.Combine(Home, "userdata");
        Directory.CreateDirectory(user);
        var start = new ProcessStartInfo(Path.Combine(Cache, "runtime", "pythonw.exe"), "\"" + Path.Combine(Cache, "pc_app.py") + "\"");
        start.WorkingDirectory = Cache; start.UseShellExecute = false; start.CreateNoWindow = true;
        start.WindowStyle = ProcessWindowStyle.Hidden;
        start.EnvironmentVariables["E7_ADVISOR_HOME"] = user;
        start.EnvironmentVariables["TCL_LIBRARY"] = Path.Combine(Cache, "runtime", "tcl", "tcl8.6");
        start.EnvironmentVariables["TK_LIBRARY"] = Path.Combine(Cache, "runtime", "tcl", "tk8.6");
        Process.Start(start);
    }
}
