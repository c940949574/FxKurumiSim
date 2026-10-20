# 久留美模拟器 · KurumiSim

日股 / 美股 / 港股 / 期货 / 外汇 的投资模拟终端。C# + WebView2 单文件，约 3.3MB，零安装。

## 特性

- 四板块：股票（日 / 美 / 港）、期货、外汇、组合绩效
- 多币种现金（CNY / JPY / USD / HKD），按实时汇率双向结汇，0.12% 点差
- 三个开局：一般韭菜（20 万 CNY）/ 久留美（1000 万 JPY）/ 神豪（1 亿 USD）
- 杠杆与保仓：分市场保证金率、追保倒计时、强平引擎、期货逐日盯市、PDT
- 行情：日 / 美 / 港走腾讯，外汇走新浪，历史日线走 Yahoo（可配置代理）
- K 线周期：1M / 5M / 10M / 日 / 周 / 月 / 季 / 年
- 存档：`文档\KurumiSim\save.json`，纯 JSON，可手改、可备份

## 目录

```
csharp/KurumiSim/        C# 宿主（WinForms + WebView2）
  Program.cs             窗口、存档 IPC、行情代理、K 线解包
  Assets/klines.bin      预置历史日线（gzip，23 个品种，5.5MB → 1.75MB）
app/renderer/index.html  前端（单文件，原生 JS，无需构建）
```

## 构建

需要 .NET 8 SDK。

```
cd csharp/KurumiSim
dotnet publish -c Release -r win-x64 --self-contained false
```

产物：`bin\Release\net8.0-windows\win-x64\publish\久留美模拟器.exe`

## 运行时数据

| 路径 | 作用 |
|---|---|
| `文档\KurumiSim\save.json` | 存档（持仓、资金、自选） |
| `文档\KurumiSim\klines\` | 历史日线缓存，首次启动自动从 exe 内解包 |
| `%LOCALAPPDATA%\KurumiSim\webview` | WebView2 缓存，可随时删除 |

## 行情与代理

国内可直连：腾讯 `qt.gtimg.cn`（日 / 美 / 港快照）、新浪 `hq.sinajs.cn`（外汇）。
Yahoo（历史日线）国内不通，默认走 `http://127.0.0.1:6789` 代理；无代理时自动回退到本地缓存与国内源。

## 环境要求

Windows 10 1803+ / Windows 11，需系统自带 .NET 8 运行时与 WebView2 运行时。

## 许可

MIT
