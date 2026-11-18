using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Launcher
{
    [STAThread]
    private static void Main()
    {
        string folder = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(folder, @"runtime\pythonw.exe");
        string app = Path.Combine(folder, "vbd.py");
        try
        {
            if (!File.Exists(python) || !File.Exists(app))
                throw new FileNotFoundException("Extract the entire ZIP and keep the app files together.");

            var launch = new ProcessStartInfo(python, "-E -s -B \"" + app + "\"")
            {
                WorkingDirectory = folder,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            Process.Start(launch).Dispose();
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Video Bulk Downloader",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
