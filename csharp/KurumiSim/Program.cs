using System.Diagnostics;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.RegularExpressions;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace KurumiSim;

internal static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        if (args != null && args.Contains("--selftest")) { MainForm.SelfTest(); return; }
        MainForm.EnsureKlines();               // 首次启动把内置日线解包到文档目录
        Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);   // 关键：否则 125%/150% 缩放下整窗被位图拉伸，字体发虚
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MainForm());
    }
}

internal sealed class MainForm : Form
{
    /// <summary>首次启动：把内嵌的日线包解到 文档\KurumiSim\klines；已有 5 个以上文件则跳过</summary>
    public static void EnsureKlines()
    {
        try
        {
            Directory.CreateDirectory(KLineDir);
            if (Directory.GetFiles(KLineDir, "*.json").Length >= 5) return;
            using var res = typeof(MainForm).Assembly.GetManifestResourceStream("klines.bin");
            if (res == null) return;
            using var gz = new System.IO.Compression.GZipStream(res, System.IO.Compression.CompressionMode.Decompress);
            using var ms = new MemoryStream();
            gz.CopyTo(ms);
            var map = JsonSerializer.Deserialize<Dictionary<string, string>>(ms.ToArray());
            if (map == null) return;
            foreach (var kv in map)
                File.WriteAllText(Path.Combine(KLineDir, SafeName(kv.Key) + ".json"), kv.Value, new UTF8Encoding(false));
            Debug.WriteLine($"klines 解包完成 {map.Count} 个");
        }
        catch (Exception ex) { Debug.WriteLine("EnsureKlines failed: " + ex.Message); }
    }

    public static void SelfTest()
    {
        var asm = typeof(MainForm).Assembly;
        var res = asm.GetManifestResourceStream("klines.bin");
        File.AppendAllText(Path.Combine(Path.GetTempPath(),"kl-selftest.txt"),"SELFTEST manifest=" + (res != null) + " bytes=" + (res?.Length ?? 0) + Environment.NewLine);
        var tmp = Path.Combine(Path.GetTempPath(), "kl-test-" + DateTime.Now.Ticks);
        Directory.CreateDirectory(tmp);
        try
        {
            using var gz = new System.IO.Compression.GZipStream(res!, System.IO.Compression.CompressionMode.Decompress);
            using var ms = new MemoryStream(); gz.CopyTo(ms);
            var map = JsonSerializer.Deserialize<Dictionary<string, string>>(ms.ToArray())!;
            foreach (var kv in map) File.WriteAllText(Path.Combine(tmp, SafeName(kv.Key) + ".json"), kv.Value, new UTF8Encoding(false));
            var total = Directory.GetFiles(tmp).Sum(f => new FileInfo(f).Length);
            File.AppendAllText(Path.Combine(Path.GetTempPath(),"kl-selftest.txt"), $"SELFTEST files={map.Count} extractedBytes={total} sample={string.Join(",", map.Keys.Take(5))}" + Environment.NewLine);
        }
        finally { try { Directory.Delete(tmp, true); } catch { } }
    }

    private readonly WebView2 _web = new() { Dock = DockStyle.Fill };
    private static readonly string SaveDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "KurumiSim");
    private static readonly string SaveFile = Path.Combine(SaveDir, "save.json");
    private static readonly string KLineDir = Path.Combine(SaveDir, "klines");
    private const string UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36";
    // 前端内嵌在程序集里，首次运行解包到临时目录，保证 exe 单文件自足
    private static string ExtractRenderer()
    {
        var dir = Path.Combine(Path.GetTempPath(), "KurumiSim", "ui");
        var asm = typeof(MainForm).Assembly;
        foreach (var name in asm.GetManifestResourceNames())
        {
            if (!name.StartsWith("renderer/")) continue;
            var rel = name.Substring("renderer/".Length).Replace('/', Path.DirectorySeparatorChar);
            var dst = Path.Combine(dir, rel);
            var parent = Path.GetDirectoryName(dst);
            if (!string.IsNullOrEmpty(parent)) Directory.CreateDirectory(parent);
            using var res = asm.GetManifestResourceStream(name);
            using var fs = File.Create(dst);
            res.CopyTo(fs);
        }
        return dir;
    }

    private static readonly HttpClient Direct = new(new HttpClientHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(20) };

    // 本地代理（设置界面可填端口，运行中即时生效）：null = 直连
    private static volatile HttpClient _proxied;
    private static string _proxySpec = "";
    private static readonly object ProxyLock = new();

    static MainForm()
    {
        Direct.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", UA);
    }

    /// <summary>归一化代理串：6789 / 127.0.0.1:6789 / http://host:port / socks5://host:port。
    /// 返回空串表示「不合法或未填」，调用方按直连处理。</summary>
    public static string NormalizeProxy(string raw)
    {
        var s = (raw ?? "").Trim();
        if (s.Length == 0) return "";
        if (Regex.IsMatch(s, @"^\d{2,5}$")) s = "127.0.0.1:" + s;                    // 只填端口
        if (!Regex.IsMatch(s, @"^[a-zA-Z][\w+.\-]*://")) s = "http://" + s;           // 缺协议
        if (!Uri.TryCreate(s, UriKind.Absolute, out var u)) return "";
        if (u.IsDefaultPort || u.Port <= 0) return "";                               // 没写端口 → 不是代理
        return u.GetLeftPart(UriPartial.Authority);
    }

    /// <summary>设置本地代理，返回归一化后的地址（空串 = 直连）。</summary>
    public static string SetProxy(string raw)
    {
        var spec = NormalizeProxy(raw);
        lock (ProxyLock)
        {
            if (spec.Length == 0) { _proxied = null; _proxySpec = ""; return ""; }
            if (spec == _proxySpec) return _proxySpec;
            try
            {
                var h = new HttpClientHandler { UseProxy = true, Proxy = new WebProxy(spec) };
                var c = new HttpClient(h) { Timeout = TimeSpan.FromSeconds(40) };
                c.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", UA);
                _proxied = c;
                _proxySpec = spec;
            }
            catch { return _proxySpec; }
            return _proxySpec;
        }
    }

    /// <summary>需要出墙的请求（Yahoo 日线）走这个：配了代理就用代理，否则直连。</summary>
    private static HttpClient Net() => _proxied ?? Direct;

    public MainForm()
    {
        Text = "久留美模拟器";
        Width = 1500; Height = 920; MinimumSize = new Size(1180, 700);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(8, 10, 14);
        AutoScaleMode = AutoScaleMode.Dpi;
        try { Icon = new Icon(Path.Combine(AppContext.BaseDirectory, "icon.ico")); } catch { }
        Controls.Add(_web);
        Load += async (_, __) => await InitAsync();
    }

    private async Task InitAsync()
    {
        // WebView2 的缓存/GPU/cookie 目录放 LocalAppData，不污染「文档」
        var udf = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "KurumiSim", "webview");
        Directory.CreateDirectory(udf);
        var env = await CoreWebView2Environment.CreateAsync(null, udf);
        await _web.EnsureCoreWebView2Async(env);
        var core = _web.CoreWebView2;
        core.Settings.AreDefaultContextMenusEnabled = false;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreDevToolsEnabled = false;

        core.SetVirtualHostNameToFolderMapping("kurumi.app", ExtractRenderer(), CoreWebView2HostResourceAccessKind.Allow);
        core.AddScriptToExecuteOnDocumentCreatedAsync(BridgeJs);
        core.WebMessageReceived += OnMessage;
        core.Navigate("https://kurumi.app/index.html");
    }

    // ---------- JS 桥：在页面里注入与 Electron 版完全一致的 window.Kurumi ----------
    private const string BridgeJs = """
        (function(){
          if (window.Kurumi && window.Kurumi.isNative) return;
          const pend = new Map(); let seq = 0;
          function call(method, ...args){
            return new Promise((resolve, reject) => {
              const id = ++seq; pend.set(id, {resolve, reject});
              window.chrome.webview.postMessage({ id, method, args });
            });
          }
          window.chrome.webview.addEventListener('message', e => {
            const m = e.data; const p = m && pend.get(m.id); if (!p) return;
            pend.delete(m.id);
            if (m.ok) p.resolve(m.result); else p.reject(new Error(m.error || 'native error'));
          });
          window.Kurumi = {
            isNative: true,
            readSave:    () => call('readSave'),
            writeSave:   (s) => call('writeSave', s),
            clearSave:   () => call('clearSave'),
            backupSave:  () => call('backupSave'),
            restoreSave: () => call('restoreSave'),
            openSaveFolder: () => call('openSaveFolder'),
            savePath:    () => call('savePath'),
            httpGet:     (u) => call('httpGet', u),
            setProxy:    (p) => call('setProxy', p),
            getProxy:    ()  => call('getProxy'),
            readKline:   (id) => call('readKline', id),
            downloadKline: (id, sym) => call('downloadKline', id, sym),
            saveKline:   (id, json) => call('saveKline', id, json),
            listKlines:  () => call('listKlines')
          };
        })();
        """;

    private async void OnMessage(object sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        string reply;
        try
        {
            using var doc = JsonDocument.Parse(e.WebMessageAsJson);
            var root = doc.RootElement;
            var id = root.GetProperty("id").GetInt64();
            var method = root.GetProperty("method").GetString();
            var args = root.TryGetProperty("args", out var a) && a.ValueKind == JsonValueKind.Array
                ? a.EnumerateArray().Select(x => x.ValueKind == JsonValueKind.String ? x.GetString() : x.ToString()).ToArray()
                : Array.Empty<string>();
            var result = await Dispatch(method, args);
            reply = JsonSerializer.Serialize(new { id, ok = true, result });
        }
        catch (Exception ex)
        {
            reply = JsonSerializer.Serialize(new { id = 0, ok = false, error = ex.Message });
        }
        _web.CoreWebView2.PostWebMessageAsJson(reply);
    }

    private async Task<object> Dispatch(string method, string[] a)
    {
        switch (method)
        {
            case "readSave": return SafeRead(SaveFile);
            case "writeSave":
                Directory.CreateDirectory(SaveDir);
                var tmp = SaveFile + ".tmp";
                File.WriteAllText(tmp, a[0], new UTF8Encoding(false));
                File.Move(tmp, SaveFile, true);
                return true;
            case "clearSave":
                if (File.Exists(SaveFile)) File.Delete(SaveFile);
                return true;
            case "backupSave": return BackupCurrent();
            case "restoreSave": return RestoreFromUserFile();
            case "openSaveFolder":
                Directory.CreateDirectory(SaveDir);
                Process.Start(new ProcessStartInfo("explorer.exe", $"\"{SaveDir}\"") { UseShellExecute = true });
                return true;
            case "savePath": return SaveFile;
            case "httpGet": return await HttpGet(a[0]);
            case "setProxy": return SetProxy(a.Length > 0 ? a[0] : "");
            case "getProxy": return _proxySpec;
            case "readKline": return SafeRead(Path.Combine(KLineDir, SafeName(a[0]) + ".json"));
            case "downloadKline": return await DownloadKline(a[0], a.Length > 1 && !string.IsNullOrWhiteSpace(a[1]) ? a[1] : a[0]);
            case "saveKline": return SaveKline(a[0], a.Length > 1 ? a[1] : "");
            case "listKlines": return ListKlines();
            default: throw new Exception("unknown method " + method);
        }
    }

    // ---------- 存档 ----------
    private static string SafeRead(string path)
    {
        try { return File.Exists(path) ? File.ReadAllText(path, Encoding.UTF8) : ""; }
        catch { return ""; }
    }

    private static string SafeName(string id) => string.Concat(id.Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c));

    private static string ShortCode(DateTime d)
    {
        const string AL = "ABCDEFGHJKLMNPQRSTUVWXYZ", MN = "0123456789XY";
        var hc = AL[Math.Min(23, d.Hour)];
        var mc = MN[d.Minute / 5];
        var t = new DateTime(d.Year, d.Month, d.Day, 0, 0, 0, DateTimeKind.Utc);
        var day = (int)t.DayOfWeek == 0 ? 7 : (int)t.DayOfWeek;
        t = t.AddDays(4 - day);
        var y0 = new DateTime(t.Year, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var wk = (int)Math.Ceiling(((t - y0).TotalDays + 1) / 7.0);
        return $"{d.Year % 100:00}{wk:00}{day}{hc}{mc}";
    }

    private static string BackupCurrent()
    {
        try
        {
            if (!File.Exists(SaveFile)) return "";
            Directory.CreateDirectory(SaveDir);
            var dst = Path.Combine(SaveDir, $"save_{ShortCode(DateTime.Now)}.json");
            File.Copy(SaveFile, dst, true);
            return dst;
        }
        catch { return ""; }
    }

    private string RestoreFromUserFile()
    {
        using var dlg = new OpenFileDialog
        {
            Title = "选择要载入的存档",
            InitialDirectory = Directory.Exists(SaveDir) ? SaveDir : Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            Filter = "存档 (*.json)|*.json|所有文件 (*.*)|*.*"
        };
        if (dlg.ShowDialog(this) != DialogResult.OK) return "canceled";
        try
        {
            var txt = File.ReadAllText(dlg.FileName, Encoding.UTF8);
            JsonDocument.Parse(txt).Dispose();          // 校验是合法 JSON
            var backup = BackupCurrent();                // 先备份原档
            Directory.CreateDirectory(SaveDir);
            File.WriteAllText(SaveFile, txt, new UTF8Encoding(false));
            BeginInvoke(() => _web.CoreWebView2.Reload());
            return string.IsNullOrEmpty(backup) ? "ok" : "ok:" + Path.GetFileName(backup);
        }
        catch (Exception ex) { return "error:" + ex.Message; }
    }

    // ---------- 行情 ----------
    private static readonly string[] AllowedHosts =
    {
        "qt.gtimg.cn", "ifzq.gtimg.cn", "web.ifzq.gtimg.cn", "hq.sinajs.cn", "stock.finance.sina.com.cn",
        "query1.finance.yahoo.com"          // 公司名查询（需走代理）
    };

    private static async Task<string> HttpGet(string url)
    {
        var uri = new Uri(url);
        if (!AllowedHosts.Contains(uri.Host)) throw new Exception("域名不在白名单");
        var req = new HttpRequestMessage(HttpMethod.Get, uri);
        var yahoo = uri.Host.EndsWith("yahoo.com", StringComparison.OrdinalIgnoreCase);
        req.Headers.Referrer = new Uri(yahoo ? "https://finance.yahoo.com/"
            : uri.Host.Contains("sina") ? "https://finance.sina.com.cn/" : "https://gu.qq.com/");
        // Yahoo 只有境外可直连：配了代理就走代理，并返回 UTF-8；国内源仍直连、GBK
        using var res = await (yahoo ? Net() : Direct).SendAsync(req);
        res.EnsureSuccessStatusCode();
        var bytes = await res.Content.ReadAsByteArrayAsync();
        return yahoo ? Encoding.UTF8.GetString(bytes) : Encoding.GetEncoding("GBK").GetString(bytes);
    }

    private static async Task<object> DownloadKline(string id, string sym)
    {
        try
        {
            var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            var url = $"https://query2.finance.yahoo.com/v8/finance/chart/{Uri.EscapeDataString(sym)}"
                    + $"?period1=946684800&period2={now}&interval=1d&events=div%2Csplits";
            using var res = await Net().GetAsync(url);
            if (!res.IsSuccessStatusCode) return new { id, n = 0, err = "HTTP " + (int)res.StatusCode };
            using var doc = JsonDocument.Parse(await res.Content.ReadAsStringAsync());
            var r = doc.RootElement.GetProperty("chart").GetProperty("result")[0];
            var ts = r.GetProperty("timestamp");
            var q = r.GetProperty("indicators").GetProperty("quote")[0];
            var o = q.GetProperty("open"); var h = q.GetProperty("high");
            var l = q.GetProperty("low"); var c = q.GetProperty("close");
            var bars = new List<double[]>();
            for (int i = 0; i < ts.GetArrayLength(); i++)
            {
                if (c[i].ValueKind == JsonValueKind.Null) continue;
                if (o[i].ValueKind == JsonValueKind.Null || h[i].ValueKind == JsonValueKind.Null || l[i].ValueKind == JsonValueKind.Null) continue;
                var cc = c[i].GetDouble();
                if (cc <= 0) continue;
                bars.Add(new[] { ts[i].GetInt64() * 1000.0, Math.Round(o[i].GetDouble(), 4), Math.Round(h[i].GetDouble(), 4), Math.Round(l[i].GetDouble(), 4), Math.Round(cc, 4) });
            }
            if (bars.Count == 0) return new { id, n = 0 };
            Directory.CreateDirectory(KLineDir);
            var payload = JsonSerializer.Serialize(new { v = 1, id, start = (long)bars[0][0], bars });
            File.WriteAllText(Path.Combine(KLineDir, SafeName(id) + ".json"), payload, new UTF8Encoding(false));
            return new { id, n = bars.Count, start = (long)bars[0][0], end = (long)bars[^1][0] };
        }
        catch (Exception ex) { return new { id, n = 0, err = ex.Message }; }
    }

    /// <summary>把渲染层从国内免费源抓到的日线落盘（与 DownloadKline 同格式），下次启动直接命中缓存</summary>
    private static object SaveKline(string id, string json)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(id) || string.IsNullOrWhiteSpace(json)) return 0;
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Array || root.GetArrayLength() < 5) return 0;
            var first = root[0];
            if (first.ValueKind != JsonValueKind.Array || first.GetArrayLength() < 5) return 0;
            var start = first[0].GetInt64();
            Directory.CreateDirectory(KLineDir);
            var payload = JsonSerializer.Serialize(new { v = 1, id, start, bars = root });
            var path = Path.Combine(KLineDir, SafeName(id) + ".json");
            var tmp = path + ".tmp";
            File.WriteAllText(tmp, payload, new UTF8Encoding(false));
            File.Move(tmp, path, true);          // 原子替换，避免中断留下半个文件
            return root.GetArrayLength();
        }
        catch { return 0; }
    }

    private static object ListKlines()
    {
        try
        {
            if (!Directory.Exists(KLineDir)) return Array.Empty<object>();
            return Directory.GetFiles(KLineDir, "*.json").Select(f =>
            {
                try
                {
                    using var doc = JsonDocument.Parse(File.ReadAllText(f));
                    var bars = doc.RootElement.GetProperty("bars");
                    return (object)new { id = doc.RootElement.GetProperty("id").GetString(), n = bars.GetArrayLength() };
                }
                catch { return null; }
            }).Where(x => x != null).ToArray();
        }
        catch { return Array.Empty<object>(); }
    }
}
