// 久留美模拟器 · Electron 主进程
// 职责：窗口、文档目录存档、带 Referer 的行情请求（绕开浏览器 CORS）
const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const fs = require('fs');
const path = require('path');

const SAVE_DIR = () => path.join(app.getPath('documents'), 'KurumiSim');
const SAVE_FILE = () => path.join(SAVE_DIR(), 'save.json');

// SAT-288 短码：YY + ISO周 + 星期 + 小时字母 + 5分钟码
function shortCode(d = new Date()) {
  const AL = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
  const MN = '0123456789XY';
  const hc = AL[Math.min(23, d.getHours())];
  const mc = MN[Math.floor(d.getMinutes() / 5)];
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  const wk = Math.ceil(((t - y0) / 86400000 + 1) / 7);
  return String(d.getFullYear()).slice(2) + String(wk).padStart(2, '0') + day + hc + mc;
}

function ensureDir() {
  const d = SAVE_DIR();
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
  return d;
}

/* ---------------- IPC：存档 ---------------- */
ipcMain.handle('save:path', () => SAVE_FILE());

ipcMain.handle('save:read', () => {
  try {
    const f = SAVE_FILE();
    return fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : '';
  } catch (e) { return ''; }
});

ipcMain.handle('save:write', (_e, str) => {
  try {
    ensureDir();
    const f = SAVE_FILE();
    const tmp = f + '.tmp';
    fs.writeFileSync(tmp, str, 'utf8');       // 先写临时文件再原子替换，避免写一半断电毁档
    fs.renameSync(tmp, f);
    return true;
  } catch (e) { return false; }
});

ipcMain.handle('save:clear', () => {
  try { const f = SAVE_FILE(); if (fs.existsSync(f)) fs.unlinkSync(f); return true; }
  catch (e) { return false; }
});

// 备份当前存档为 save_<短码>.json
ipcMain.handle('save:backup', () => {
  try {
    const f = SAVE_FILE();
    if (!fs.existsSync(f)) return '';
    const out = path.join(SAVE_DIR(), `save_${shortCode()}.json`);
    fs.copyFileSync(f, out);
    return out;
  } catch (e) { return ''; }
});

// 手动载入：先备份原档，再用所选文件覆盖，然后重载窗口
ipcMain.handle('save:restore', async (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  const r = await dialog.showOpenDialog(win, {
    title: '选择要载入的存档',
    defaultPath: ensureDir(),
    filters: [{ name: '存档', extensions: ['json'] }],
    properties: ['openFile']
  });
  if (r.canceled || !r.filePaths[0]) return { ok: false, reason: 'canceled' };
  try {
    const src = r.filePaths[0];
    const txt = fs.readFileSync(src, 'utf8');
    JSON.parse(txt);                                     // 先校验是合法 JSON
    const f = SAVE_FILE();
    let backup = '';
    if (fs.existsSync(f)) {                               // 原档先按短码备份
      backup = path.join(SAVE_DIR(), `save_${shortCode()}.json`);
      fs.copyFileSync(f, backup);
    }
    fs.writeFileSync(f, txt, 'utf8');
    if (win) setTimeout(() => win.webContents.reload(), 120);
    return { ok: true, backup: backup ? path.basename(backup) : '' };
  } catch (err) {
    return { ok: false, reason: String(err.message || err) };
  }
});

ipcMain.handle('save:openFolder', () => {
  ensureDir();
  shell.openPath(SAVE_DIR());
  return true;
});

/* ---------------- IPC：行情（主进程取数，带 Referer，绕 CORS） ---------------- */
ipcMain.handle('http:get', async (_e, url) => {
  if (typeof url !== 'string' || !/^https:\/\/(qt\.gtimg\.cn|web\.ifzq\.gtimg\.cn|hq\.sinajs\.cn|ifzq\.gtimg\.cn|stock\.finance\.sina\.com\.cn)\//.test(url)) {
    throw new Error('域名不在白名单');
  }
  const isSina = url.includes('sinajs.cn');
  const res = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36',
      'Referer': isSina ? 'https://finance.sina.com.cn/' : 'https://gu.qq.com/',
      'Accept': '*/*'
    },
    signal: AbortSignal.timeout(8000)
  });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const buf = Buffer.from(await res.arrayBuffer());
  return new TextDecoder('gbk').decode(buf);   // 腾讯/新浪均为 GBK
});

/* ---------------- IPC：历史日线（走 6789 代理拉 Yahoo，落盘缓存） ---------------- */
const { session, net } = require('electron');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36';
const KDIR = () => path.join(SAVE_DIR(), 'klines');

let yahooSess = null;
function yahooSession() {
  if (!yahooSess) {
    yahooSess = session.fromPartition('persist:yahoo-proxy');
    yahooSess.setProxy({ proxyRules: 'http://127.0.0.1:6789' });
  }
  return yahooSess;
}

async function yahooDaily(sym) {
  const now = Math.floor(Date.now() / 1000);
  const url = `https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}`
    + `?period1=946684800&period2=${now}&interval=1d&events=div%2Csplits`;
  const res = await net.fetch(url, { session: yahooSession(), headers: { 'User-Agent': UA, 'Accept': 'application/json' } });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const j = await res.json();
  const r = j && j.chart && j.chart.result && j.chart.result[0];
  if (!r || !r.timestamp) return [];
  const q = r.indicators.quote[0] || {};
  const out = [];
  for (let i = 0; i < r.timestamp.length; i++) {
    const c = q.close ? q.close[i] : null;
    const o = q.open ? q.open[i] : null;
    const h = q.high ? q.high[i] : null;
    const l = q.low ? q.low[i] : null;
    // OHLC 任一缺失就跳过，避免用收盘价填出一堆 1 像素横线
    if (!(c > 0) || !(o > 0) || !(h > 0) || !(l > 0)) continue;
    out.push([r.timestamp[i] * 1000, +o.toFixed(4), +h.toFixed(4), +l.toFixed(4), +c.toFixed(4)]);
  }
  return out;
}

ipcMain.handle('kl:read', (_e, id) => {
  try {
    const f = path.join(KDIR(), id.replace(/[\\/:*?"<>|]/g, '_') + '.json');
    return fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : '';
  } catch (e) { return ''; }
});

ipcMain.handle('kl:download', async (_e, id, yahooSym) => {
  try {
    const bars = await yahooDaily(yahooSym || id);
    if (!bars.length) return { id, n: 0 };
    if (!fs.existsSync(KDIR())) fs.mkdirSync(KDIR(), { recursive: true });
    const f = path.join(KDIR(), id.replace(/[\\/:*?"<>|]/g, '_') + '.json');
    fs.writeFileSync(f, JSON.stringify({ v: 1, id, start: bars[0][0], bars }), 'utf8');
    return { id, n: bars.length, start: bars[0][0], end: bars[bars.length - 1][0] };
  } catch (e) { return { id, n: 0, err: String(e.message || e) }; }
});

ipcMain.handle('kl:list', () => {
  try {
    if (!fs.existsSync(KDIR())) return [];
    return fs.readdirSync(KDIR()).filter(f => f.endsWith('.json'))
      .map(f => { try { const j = JSON.parse(fs.readFileSync(path.join(KDIR(), f), 'utf8')); return { id: j.id, n: j.bars.length, start: j.start }; } catch (e) { return null; } })
      .filter(Boolean);
  } catch (e) { return []; }
});

/* ---------------- 窗口 ---------------- */
let win = null;
function createWindow() {
  win = new BrowserWindow({
    width: 1500, height: 920, minWidth: 1180, minHeight: 700,
    backgroundColor: '#080A0E',
    title: '久留美模拟器',
    autoHideMenuBar: true,
    icon: path.join(__dirname, 'build', 'icon.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false
    }
  });
  win.setMenuBarVisibility(false);
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  win.on('closed', () => { win = null; });
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) { if (win.isMinimized()) win.restore(); win.focus(); }
  });
  app.whenReady().then(createWindow);
  app.on('window-all-closed', () => app.quit());
}
