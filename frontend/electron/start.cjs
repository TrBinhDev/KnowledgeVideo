const { spawn } = require("node:child_process");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;
const child = spawn(require("electron"), [root], { cwd: root, env, stdio: "inherit" });
child.on("exit", (code) => { process.exitCode = code || 0; });
child.on("error", (error) => { console.error(error); process.exitCode = 1; });
process.on("SIGINT", () => child.kill());
process.on("SIGTERM", () => child.kill());
