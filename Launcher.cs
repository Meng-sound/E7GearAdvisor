using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
internal static class Program {
  [STAThread] private static void Main() {
    string folder=AppDomain.CurrentDomain.BaseDirectory;
    string python=Path.Combine(folder,"runtime","pythonw.exe");
    string script=Path.Combine(folder,"pc_app.py");
    if (!File.Exists(python) || !File.Exists(script)) {
      MessageBox.Show("Extract the complete portable ZIP into one folder before starting.","装备强化计算器"); return;
    }
    try {
      var start=new ProcessStartInfo(python,"\""+script+"\"");
      start.WorkingDirectory=folder; start.UseShellExecute=false;
      start.CreateNoWindow=true; start.WindowStyle=ProcessWindowStyle.Hidden;
      start.EnvironmentVariables["TCL_LIBRARY"]=Path.Combine(folder,"runtime","tcl","tcl8.6");
      start.EnvironmentVariables["TK_LIBRARY"]=Path.Combine(folder,"runtime","tcl","tk8.6");
      Process.Start(start);
    } catch(Exception error) { MessageBox.Show(error.Message,"装备强化计算器"); }
  }
}
