import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

// Global teardown (playwright.config.js): prune the per-process capture scratch trees the heavy
// tutorial-shots specs and the capture tool leave under repo-root tmp/. The tool self-cleans its
// scratch on a CLEAN --check but intentionally RETAINS tmp/tutorial-shots-check/<pid> on a STALE
// result (for debugging), so the stale-detection tests would otherwise leak a tree per run. This
// runs once, AFTER every test in the invocation completes, so it is race-free (unlike a per-worker
// afterAll wiping a shared parent) and can safely remove the shared scratch parents. tmp/ is
// gitignored and disposable; this just keeps local dev clean (CI runners are ephemeral).
export default function globalTeardown() {
  const DEV = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const REPO = path.resolve(DEV, "..", "..", "..");
  for (const name of ["tutorial-shots-check", "tutorial-shots-generate", "tutorial-shots-spec"]) {
    fs.rmSync(path.join(REPO, "tmp", name), { recursive: true, force: true });
  }
}
