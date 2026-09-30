const { spawn } = require("node:child_process");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const nextBin = path.join(root, "node_modules", "next", "dist", "bin", "next");
const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;

let build;
let electron;
let stopping = false;

function stop() {
  if (stopping) return;
  stopping = true;
  if (electron && !electron.killed) electron.kill();
  if (build && !build.killed) build.kill();
}

build = spawn(process.execPath, [nextBin, "build"], {
  cwd: root, stdio: "inherit", windowsHide: true,
});
build.on("error", (error) => { console.error("Next.js build failed:", error); stop(); process.exitCode = 1; });
build.on("exit", (code) => {
  if (stopping) return;
  if (code !== 0) { process.exitCode = code || 1; return; }
  electron = spawn(require("electron"), [root], { cwd: root, env, stdio: "inherit" });
  electron.on("error", (error) => { console.error("Electron failed:", error); process.exitCode = 1; });
  electron.on("exit", (exitCode) => { process.exitCode = exitCode || 0; });
});

process.on("SIGINT", stop);
process.on("SIGTERM", stop);
