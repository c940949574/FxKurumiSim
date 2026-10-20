// 渲染进程与主进程之间的最小桥：只暴露存档与行情查询
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('Kurumi', {
  isNative: true,
  readSave: () => ipcRenderer.invoke('save:read'),
  writeSave: (str) => ipcRenderer.invoke('save:write', str),
  clearSave: () => ipcRenderer.invoke('save:clear'),
  backupSave: () => ipcRenderer.invoke('save:backup'),
  restoreSave: () => ipcRenderer.invoke('save:restore'),
  openSaveFolder: () => ipcRenderer.invoke('save:openFolder'),
  savePath: () => ipcRenderer.invoke('save:path'),
  httpGet: (url) => ipcRenderer.invoke('http:get', url),
  readKline: (id) => ipcRenderer.invoke('kl:read', id),
  downloadKline: (id, sym) => ipcRenderer.invoke('kl:download', id, sym),
  listKlines: () => ipcRenderer.invoke('kl:list')
});
