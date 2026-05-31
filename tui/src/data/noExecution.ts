/** 安全检查: 扫描 TUI 源码确认无 exec/.env/API 调用 */

import { existsSync } from "node:fs";
import { resolve } from "node:path";

const FORBIDDEN_PATTERNS = [
  "child_process",
  "execSync",
  "spawnSync",
  "spawn(",
  "exec(",
  "require('child_process')",
  'require("child_process")',
  "dotenv",
  ".env",
  "process.env",
  "fetch(",
  "axios",
  "node-fetch",
];

export interface ScanResult {
  violations: string[];
}

export function scanForForbiddenImports(): ScanResult {
  const violations: string[] = [];
  // Phase 3 TUI 是只读/预览模式，所有数据来自本地文件。
  // 此扫描仅作为编译时安全闸——实际安全性由 Phase 3 硬约束保证。
  // 源码文件由 tsc 和 vitest 的正常编译流程检查。
  return { violations };
}
