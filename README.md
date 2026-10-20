# FxKurumiSim · 久留美模拟器

A trading simulator for Japanese / US / Hong Kong stocks, futures and FX.
C# + WebView2 single-file build, ~3.3 MB, no installer required.

日股 / 美股 / 港股 / 期货 / 外汇的投资模拟终端。C# + WebView2 单文件，约 3.3MB，双击即用。

[English](#english) · [中文](#chinese)

---

## English

### Features

- Four boards: equities (JP / US / HK), futures, FX, portfolio performance
- Multi-currency cash (CNY / JPY / USD / HKD) with two-way conversion at live rates, 0.12% spread
- Three starting scenarios: Retail Rookie (CNY 200k) / Kurumi (JPY 10M) / Whale (USD 100M)
- Leverage presets 1× / 5× / 10× / 50× (FX also 100×)
- **Third-party leverage**: exceed the regulatory cap (JP 3.33×, US 2×, HK 2.5×) up to 50× (FX 100×).
  Requires explicit confirmation; charges a 0.5% opening commission and +2%/yr financing,
  with maintenance margin scaled to `0.6 / leverage`
- Margin protection: margin call countdown, forced liquidation, daily mark-to-market on futures, US PDT rule
- Chart intervals: 1M / 5M / 10M / 1D / 1W / 1M / 1Q / 1Y
- 23 instruments' daily history (from 2000) embedded; extracted on first launch

### Build

```
cd csharp/KurumiSim
dotnet publish -c Release -r win-x64 --self-contained false
```

Output: `bin\Release\net8.0-windows\win-x64\publish\久留美模拟器.exe`

### Runtime data

| Path | Purpose |
|---|---|
| `Documents\KurumiSim\save.json` | Save file (positions, cash, custom symbols) |
| `Documents\KurumiSim\klines\` | Daily bar cache, auto-extracted on first launch |
| `%LOCALAPPDATA%\KurumiSim\webview` | WebView2 cache, safe to delete |

### Market data

Directly reachable in mainland China: Tencent `qt.gtimg.cn` (JP/US/HK quotes), Sina `hq.sinajs.cn` (FX).
Yahoo (daily history) is blocked; the app defaults to a local proxy at `http://127.0.0.1:6789`
and falls back to local cache / domestic sources when unavailable.

### Requirements

Windows 10 1803+ / Windows 11 with the .NET 8 runtime and WebView2 runtime (both ship with the OS).

---

<a id="chinese"></a>
## 中文

### 特性

- 四板块：股票（日 / 美 / 港）、期货、外汇、组合绩效
- 多币种现金（CNY / JPY / USD / HKD），按实时汇率双向结汇，0.12% 点差
- 三个开局：一般韭菜（20 万 CNY）/ 久留美（1000 万 JPY）/ 神豪（1 亿 USD）
- 杠杆档位 1× / 5× / 10× / 50×（外汇另加 100×）
- **第三方杠杆**：可突破监管上限（日股 3.33×、美股 2×、港股 2.5×）最高到 50×（外汇 100×），
  需二次确认，收 0.5% 开仓佣金、融资利率上浮 2%/年，维持保证金率按 `0.6 / 杠杆` 下调
- 保仓机制：追保倒计时、强平引擎、期货逐日盯市、美股 PDT
- K 线周期：1M / 5M / 10M / 日 / 周 / 月 / 季 / 年
- 内嵌 23 个品种历史日线（2000 年起），首次启动自动解包到本地

### 构建

```
cd csharp/KurumiSim
dotnet publish -c Release -r win-x64 --self-contained false
```

产物：`bin\Release\net8.0-windows\win-x64\publish\久留美模拟器.exe`

### 数据位置

| 路径 | 作用 |
|---|---|
| `文档\KurumiSim\save.json` | 存档（持仓、资金、自选） |
| `文档\KurumiSim\klines\` | 历史日线缓存，首次启动自动从 exe 内解包 |
| `%LOCALAPPDATA%\KurumiSim\webview` | WebView2 缓存，可随时删除 |

### 行情与代理

国内可直连：腾讯 `qt.gtimg.cn`（日 / 美 / 港快照）、新浪 `hq.sinajs.cn`（外汇）。
Yahoo（历史日线）国内不通，默认走 `http://127.0.0.1:6789` 代理；无代理时自动回退到本地缓存与国内源。

### 环境要求

Windows 10 1803+ / Windows 11，需系统自带 .NET 8 运行时与 WebView2 运行时。

---

---

## License · 许可

MIT
