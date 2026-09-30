const { app, BrowserWindow, clipboard, dialog, ipcMain, net, protocol, shell } = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const frontend = path.resolve(__dirname, "..");
const project = path.resolve(frontend, "..");
const exported = path.join(frontend, "out");
const development = process.env.KV_FRONTEND_DEV === "1";
const allowedMethods = new Set([
  "bootstrap", "list_runs", "open_run", "list_models", "settings", "save_settings", "clear_cache", "load_document", "parse_json", "parse_source",
  "suggest_topics", "create_run", "save_run", "make_outline", "update_outline", "write_script", "fit_script",
  "split_scenes", "fetch_images", "replace_image", "search_clips", "prepare_clips", "reassign_clips",
  "choose_shot", "use_picture", "set_logos", "render_preview", "gallery", "render_video", "auto_generate", "export_video", "get_credits",
]);

protocol.registerSchemesAsPrivileged([
  { scheme: "kvapp", privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } },
  { scheme: "kvmedia", privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } },
]);

let window;
let backend;
let outputRoot = path.join(project, "output");
let counter = 0;
let stdoutBuffer = "";
const pending = new Map();
const media = new Map();
const chunks = new Map();

function inside(root, target) {
  const relative = path.relative(path.resolve(root), path.resolve(target));
  return relative === "" || (!relative.startsWith(".." + path.sep) && relative !== ".." && !path.isAbsolute(relative));
}

function senderAllowed(event) {
  const url = event.senderFrame?.url || "";
  return url.startsWith("kvapp://local/") || (development && url.startsWith("http://127.0.0.1:3174/"));
}

function pythonExecutable() {
  if (process.env.KV_PYTHON) return process.env.KV_PYTHON;
  const venv = path.join(project, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  return fs.existsSync(venv) ? venv : process.platform === "win32" ? "python" : "python3";
}

function startBackend() {
  if (backend && !backend.killed) return;
  backend = spawn(pythonExecutable(), ["-u", path.join(frontend, "backend.py")], {
    cwd: project, windowsHide: true, stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env, PYTHONIOENCODING: "utf-8", QT_QPA_PLATFORM: "offscreen" },
  });
  stdoutBuffer = "";
  backend.stdout.setEncoding("utf8");
  backend.stdout.on("data", (chunk) => {
    stdoutBuffer += chunk;
    while (stdoutBuffer.includes("\n")) {
      const end = stdoutBuffer.indexOf("\n");
      const line = stdoutBuffer.slice(0, end);
      stdoutBuffer = stdoutBuffer.slice(end + 1);
      if (!line.trim()) continue;
      let message;
      try { message = JSON.parse(line); }
      catch { console.error("Invalid Python response:", line.slice(0, 300)); continue; }
      if (message.type === "chunk") {
        const gathered = (chunks.get(message.id) || "") + message.data;
        if (!message.last) { chunks.set(message.id, gathered); continue; }
        chunks.delete(message.id);
        try { message = JSON.parse(gathered); }
        catch { console.error("Invalid chunked Python response"); continue; }
      }
      if (message.type === "progress") {
        window?.webContents.send("kv:progress", message);
        continue;
      }
      if (message.id === undefined) continue;
      const waiter = pending.get(message.id);
      if (!waiter) continue;
      pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error));
      else {
        if (message.result?.output_dir) outputRoot = path.resolve(message.result.output_dir);
        waiter.resolve(message.result);
      }
    }
  });
  backend.stderr.setEncoding("utf8");
  backend.stderr.on("data", (value) => console.error("Python:", value.trimEnd()));
  backend.on("error", (error) => {
    for (const waiter of pending.values()) waiter.reject(error);
    pending.clear();
    chunks.clear();
  });
  backend.on("exit", (code) => {
    for (const waiter of pending.values()) waiter.reject(new Error(`Python backend stopped (${code}).`));
    pending.clear();
    chunks.clear();
    backend = undefined;
  });
}

function callBackend(method, params = {}) {
  if (!allowedMethods.has(method)) return Promise.reject(new Error("Unknown backend action."));
  startBackend();
  const id = ++counter;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    backend.stdin.write(JSON.stringify({ id, method, params }) + "\n", "utf8", (error) => {
      if (error) { pending.delete(id); reject(error); }
    });
  });
}

function registerProtocols() {
  protocol.handle("kvapp", (request) => {
    const url = new URL(request.url);
    const requestPath = decodeURIComponent(url.pathname);
    const target = path.resolve(exported, "." + requestPath, requestPath.endsWith("/") ? "index.html" : "");
    if (!inside(exported, target)) return new Response("Forbidden", { status: 403 });
    const file = fs.existsSync(target) && fs.statSync(target).isFile() ? target : path.join(exported, "index.html");
    return net.fetch(pathToFileURL(file).toString());
  });
  protocol.handle("kvmedia", (request) => {
    const token = new URL(request.url).pathname.slice(1);
    const file = media.get(token);
    if (!file || !inside(outputRoot, file) || !fs.existsSync(file)) return new Response("Not found", { status: 404 });
    return net.fetch(pathToFileURL(file).toString());
  });
}

function makeWindow() {
  window = new BrowserWindow({
    width: 1440, height: 930, minWidth: 1060, minHeight: 700,
    backgroundColor: "#f4f6fb", title: "KnowledgeVideo",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      nodeIntegration: false, contextIsolation: true, sandbox: true,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("render-process-gone", (_event, details) => console.error("Renderer process gone:", details.reason));
  window.webContents.on("did-fail-load", (_event, code, description, url) => console.error("Page load failed:", code, description, url));
  window.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith("kvapp://local/") && !(development && url.startsWith("http://127.0.0.1:3174/"))) event.preventDefault();
  });
  if (development) window.loadURL("http://127.0.0.1:3174/");
  else window.loadURL("kvapp://local/index.html");
}

app.whenReady().then(() => {
  registerProtocols();
  ipcMain.handle("kv:call", (event, method, params) => {
    if (!senderAllowed(event)) throw new Error("Untrusted renderer.");
    return callBackend(method, params);
  });
  ipcMain.handle("kv:cancel", (event) => {
    if (!senderAllowed(event)) throw new Error("Untrusted renderer.");
    if (backend && !backend.killed) backend.stdin.write(JSON.stringify({ method: "cancel" }) + "\n");
    return true;
  });
  ipcMain.handle("kv:choose-file", async (event, kind) => {
    if (!senderAllowed(event)) throw new Error("Untrusted renderer.");
    const filters = {
      document: [{ name: "Tài liệu", extensions: ["txt", "md", "docx", "pdf"] }],
      script: [{ name: "Kịch bản JSON", extensions: ["json"] }],
      music: [{ name: "Nhạc nền", extensions: ["mp3", "wav", "m4a"] }],
      font: [{ name: "Font", extensions: ["ttf", "otf"] }],
    };
    const result = await dialog.showOpenDialog(window, { properties: ["openFile"], filters: filters[kind] || [] });
    return result.canceled ? "" : result.filePaths[0];
  });
  ipcMain.handle("kv:choose-folder", async (event) => {
    if (!senderAllowed(event)) throw new Error("Untrusted renderer.");
    const result = await dialog.showOpenDialog(window, { properties: ["openDirectory"] });
    return result.canceled ? "" : result.filePaths[0];
  });
  ipcMain.handle("kv:save-video", async (event, name) => {
    if (!senderAllowed(event)) throw new Error("Untrusted renderer.");
    const safe = String(name || "video").replace(/[\\/:*?"<>|]/g, "-").slice(0, 80);
    const result = await dialog.showSaveDialog(window, { defaultPath: `${safe}.mp4`, filters: [{ name: "MP4", extensions: ["mp4"] }] });
    return result.canceled ? "" : result.filePath;
  });
  ipcMain.handle("kv:open-path", (event, value) => {
    if (!senderAllowed(event)) throw new Error("Untrusted renderer.");
    const file = path.resolve(String(value || ""));
    if (!inside(outputRoot, file) || !fs.existsSync(file)) throw new Error("File is outside the output directory.");
    return shell.openPath(file);
  });
  ipcMain.handle("kv:open-external", (event, value) => {
    if (!senderAllowed(event)) throw new Error("Untrusted renderer.");
    const url = new URL(String(value || ""));
    if (url.protocol !== "https:" || !["youtube.com", "www.youtube.com", "youtu.be"].includes(url.hostname)) throw new Error("Invalid video URL.");
    return shell.openExternal(url.toString());
  });
  ipcMain.handle("kv:copy-text", (event, value) => {
    if (!senderAllowed(event)) throw new Error("Untrusted renderer.");
    clipboard.writeText(String(value || ""));
    return true;
  });
  ipcMain.handle("kv:media-url", (event, value) => {
    if (!senderAllowed(event)) throw new Error("Untrusted renderer.");
    const file = path.resolve(String(value || ""));
    if (!inside(outputRoot, file) || !fs.existsSync(file)) return "";
    const token = crypto.randomUUID();
    media.set(token, file);
    if (media.size > 2000) media.delete(media.keys().next().value);
    return `kvmedia://asset/${token}`;
  });
  makeWindow();
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) makeWindow(); });
});

app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
app.on("before-quit", () => { if (backend && !backend.killed) backend.kill(); });
