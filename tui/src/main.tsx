import React from "react";
import { render, useInput, useApp } from "ink";
import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";

import { Dashboard } from "./components/Dashboard";
import { parseProjectStatus } from "./data/projectStatus";
import { parseProgressLedger } from "./data/progressLedger";
import { parseDogfoodResult } from "./data/dogfoodResults";
import { buildGitInfo } from "./data/gitInfo";

const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..");

function readOrEmpty(filePath: string): string {
  try {
    return fs.readFileSync(filePath, "utf-8");
  } catch {
    return "";
  }
}

function readJsonOrNull(filePath: string): Record<string, unknown> | null {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf-8"));
  } catch {
    return null;
  }
}

function loadDogfoodResults(): ReturnType<typeof parseDogfoodResult>[] {
  const dogfoodDir = path.join(REPO_ROOT, "docs", "dogfood");
  let files: string[] = [];
  try {
    files = fs.readdirSync(dogfoodDir).filter((f) => f.endsWith(".json"));
  } catch {
    return [];
  }

  const withMtime = files
    .map((f) => {
      const fullPath = path.join(dogfoodDir, f);
      try {
        const stat = fs.statSync(fullPath);
        return { file: f, mtime: stat.mtimeMs };
      } catch {
        return { file: f, mtime: 0 };
      }
    })
    .sort((a, b) => b.mtime - a.mtime);

  return withMtime.slice(0, 5).flatMap(({ file }) => {
    const json = readJsonOrNull(path.join(dogfoodDir, file));
    if (!json) return [];
    return [parseDogfoodResult(file, json)];
  });
}

function loadGitInfo(): ReturnType<typeof buildGitInfo> {
  let branch = "";
  let headCommit = "";
  let statusStdout = "";
  let logStdout = "";

  try {
    branch = execSync("git branch --show-current", {
      cwd: REPO_ROOT,
      encoding: "utf-8",
    }).trim();
  } catch { /* ignore */ }

  try {
    headCommit = execSync("git rev-parse HEAD", {
      cwd: REPO_ROOT,
      encoding: "utf-8",
    }).trim();
  } catch { /* ignore */ }

  try {
    statusStdout = execSync("git status --short", {
      cwd: REPO_ROOT,
      encoding: "utf-8",
    }).trim();
  } catch { /* ignore */ }

  try {
    logStdout = execSync("git log --oneline -n 10", {
      cwd: REPO_ROOT,
      encoding: "utf-8",
    }).trim();
  } catch { /* ignore */ }

  return buildGitInfo(branch, headCommit, statusStdout, logStdout);
}

function App() {
  const { exit } = useApp();

  useInput((input) => {
    if (input === "q") {
      exit();
    }
  });

  const projectStatusDoc = readOrEmpty(
    path.join(REPO_ROOT, "docs", "PROJECT_STATUS.md"),
  );
  const progressLedgerDoc = readOrEmpty(
    path.join(REPO_ROOT, "docs", "PROGRESS_LEDGER.md"),
  );

  const status = parseProjectStatus(projectStatusDoc);
  const ledger = parseProgressLedger(progressLedgerDoc);
  const dogfood = loadDogfoodResults();
  const git = loadGitInfo();

  return (
    <Dashboard status={status} ledger={ledger} dogfood={dogfood} git={git} />
  );
}

render(<App />);
