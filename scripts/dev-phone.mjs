import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";

const configuredToken = process.env.DONE_API_AUTH_TOKEN?.trim();
const token = configuredToken || randomBytes(32).toString("hex");
if (token.length < 32) {
  throw new Error("DONE_API_AUTH_TOKEN must contain at least 32 characters.");
}

const env = {
  ...process.env,
  DONE_API_AUTH_ENABLED: "true",
  DONE_API_AUTH_TOKEN: token,
  EXPO_PUBLIC_API_ACCESS_TOKEN: token,
};
const command = process.platform === "win32" ? "npm.cmd" : "npm";
const children = [
  spawn(command, ["run", "api:phone"], { env, stdio: "inherit" }),
  spawn(command, ["run", "mobile"], { env, stdio: "inherit" }),
];
let stopping = false;

function stop(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (!child.killed) child.kill("SIGTERM");
  }
  process.exitCode = exitCode;
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => stop(0));
}
for (const child of children) {
  child.on("error", (error) => {
    console.error(error.message);
    stop(1);
  });
  child.on("exit", (code, signal) => {
    if (!stopping) stop(signal ? 1 : (code ?? 1));
  });
}
