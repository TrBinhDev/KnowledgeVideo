const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("kv", {
  call: (method, params = {}) => ipcRenderer.invoke("kv:call", method, params),
  cancel: () => ipcRenderer.invoke("kv:cancel"),
  chooseFile: (kind) => ipcRenderer.invoke("kv:choose-file", kind),
  chooseFolder: () => ipcRenderer.invoke("kv:choose-folder"),
  saveVideo: (name) => ipcRenderer.invoke("kv:save-video", name),
  openPath: (path) => ipcRenderer.invoke("kv:open-path", path),
  openExternal: (url) => ipcRenderer.invoke("kv:open-external", url),
  copyText: (value) => ipcRenderer.invoke("kv:copy-text", value),
  mediaUrl: (path) => ipcRenderer.invoke("kv:media-url", path),
  onProgress: (callback) => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on("kv:progress", listener);
    return () => ipcRenderer.removeListener("kv:progress", listener);
  },
});
