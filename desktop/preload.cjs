const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  platform: process.platform,
  isCompact: process.argv.includes("--compact-window"),
  isCompactModeActive: () => ipcRenderer.invoke("compact:is-active"),
  enterCompact: (opts) => ipcRenderer.invoke("compact:enter", opts || {}),
  exitCompact: () => ipcRenderer.invoke("compact:exit"),
});
