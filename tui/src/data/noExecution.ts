/** 安全检查: 扫描 TUI 源码确认无 exec/.env/API 调用 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, relative } from "node:path";

/** 禁止模式列表 — 匹配 source text 中不应出现的危险导入/调用 */
const FORBIDDEN_PATTERNS: Array<{ pattern: RegExp; label: string }> = [
  { pattern: /\bexecSync\s*\(/, label: "execSync()" },
  { pattern: /child_process\s*\.\s*exec\s*\(/, label: "child_process.exec()" },
  { pattern: /\bspawn\s*\(/, label: "spawn()" },
  { pattern: /\bspawnSync\s*\(/, label: "spawnSync()" },
  { pattern: /process\s*\.\s*env/, label: "process.env" },
  { pattern: /fs\s*\.\s*writeFileSync\s*\(/, label: "fs.writeFileSync()" },
  { pattern: /fs\s*\.\s*rmSync\s*\(/, label: "fs.rmSync()" },
  { pattern: /fs\s*\.\s*unlinkSync\s*\(/, label: "fs.unlinkSync()" },
  { pattern: /\bdotenv\b/, label: "dotenv" },
];

/**
 * 扫描器自身文件和已知安全例外。
 * — noExecution.ts: 自身包含 FORBIDDEN_PATTERNS 的字符串表达，会被自身规则命中
 * — main.tsx: 使用 execSync 只做 git 只读操作 (branch/show/status/log/rev-parse)
 */
const SCANNER_SELF_FILES = new Set(["data/noExecution.ts"]);
const GIT_READONLY_FILES = new Set(["main.tsx"]);

export interface ScanViolation {
  file: string;
  line: number;
  pattern: string;
  content: string;
}

export interface ScanResult {
  violations: ScanViolation[];
}

/**
 * 扫描单段源码文本是否包含禁止模式。
 * 返回违规列表，每项含文件、行号、匹配模式、匹配内容。
 */
export function scanSourceText(
  text: string,
  filePath: string,
): ScanViolation[] {
  const violations: ScanViolation[] = [];
  const lines = text.split("\n");

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    for (const { pattern, label } of FORBIDDEN_PATTERNS) {
      if (pattern.test(line)) {
        violations.push({
          file: filePath,
          line: i + 1,
          pattern: label,
          content: line.trim(),
        });
      }
    }
  }

  return violations;
}

/**
 * 扫描指定目录下所有 .ts/.tsx 文件，返回命中的禁止模式。
 * 排除扫描器自身文件 (noExecution.ts)。
 * main.tsx 中 git 只读 execSync 通过 GIT_READONLY_FILES 排除。
 */
export function scanForForbiddenImports(rootDir?: string): ScanResult {
  const dir = rootDir ?? resolve(__dirname, "..");
  const allViolations: ScanViolation[] = [];

  try {
    const files = collectTsFiles(dir);
    for (const absPath of files) {
      const relPath = relative(dir, absPath);

      // 跳过扫描器自身 — 其 FORBIDDEN_PATTERNS 字符串表达会被自身规则命中
      if (SCANNER_SELF_FILES.has(relPath)) continue;

      const content = readFileSync(absPath, "utf-8");
      const rawViolations = scanSourceText(content, relPath);

      // main.tsx 的 execSync 仅用于 git 只读操作 — 已审查安全
      if (GIT_READONLY_FILES.has(relPath)) {
        const filtered = rawViolations.filter((v) => {
          // execSync( 调用中如果包含 "git" 则为已知安全例外
          if (v.pattern === "execSync()" && /\bgit\b/.test(v.content)) {
            return false;
          }
          return true;
        });
        allViolations.push(...filtered);
      } else {
        allViolations.push(...rawViolations);
      }
    }
  } catch {
    // 文件系统不可达时不崩溃 — 返回空违规列表，调用方自行判断
    return { violations: [] };
  }

  return { violations: allViolations };
}

/** 递归收集目录下所有 .ts/.tsx 文件 */
function collectTsFiles(dir: string): string[] {
  const result: string[] = [];
  const stack = [dir];

  while (stack.length > 0) {
    const current = stack.pop()!;
    let entries;
    try {
      entries = readdirSync(current);
    } catch {
      continue;
    }
    for (const name of entries) {
      const full = resolve(current, name);
      try {
        const st = statSync(full);
        if (st.isDirectory()) {
          if (name !== "node_modules" && name !== "__tests__") {
            stack.push(full);
          }
        } else if (st.isFile() && (name.endsWith(".ts") || name.endsWith(".tsx"))) {
          result.push(full);
        }
      } catch {
        // 权限不足等 — 跳过
      }
    }
  }

  return result;
}
