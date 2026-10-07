// Reuse the core's PreparedPaper/evidence validation; do not duplicate its schema here.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const skillRoot = fileURLToPath(new URL("../../", import.meta.url));

export function loadV3CaptureBinding(options) {
  try {
    const raw = execFileSync("uv", ["run", "--offline", "--no-sync", "python", "-m",
      "paper_reader.official_cli", "analysis", "capture-binding",
      "--run-root", path.resolve(options.runRoot),
      "--coordination-root", path.resolve(options.coordinationRoot),
      "--prepared", options.prepared], {
      cwd: skillRoot, encoding: "utf8", timeout: 60000, maxBuffer: 64 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const result = JSON.parse(raw);
    if (result.schema_version !== "paper_reader.command-result.v3" ||
        result.command !== "analysis capture-binding" || result.ok !== true) {
      throw new Error("invalid core response");
    }
    return result.data;
  } catch {
    // Never expose subprocess output, source content, or environment in diagnostics.
    throw new Error("v3 prepared evidence binding failed");
  }
}
