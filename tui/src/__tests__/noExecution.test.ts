import { describe, it, expect } from "vitest";
import { scanForForbiddenImports, scanSourceText } from "../data/noExecution";

describe("No-execution safety gate", () => {
  describe("scanSourceText (unit — synthetic input)", () => {
    it("detects child_process.exec in source text", () => {
      const violations = scanSourceText(
        `const { exec } = require("child_process");\nchild_process.exec("rm -rf /");`,
        "fake.ts",
      );
      expect(violations.length).toBeGreaterThanOrEqual(1);
      expect(violations.some((v) => v.pattern.includes("exec("))).toBe(true);
    });

    it("detects child_process.execSync in source text", () => {
      const violations = scanSourceText(
        `execSync("rm -rf /");`,
        "fake.ts",
      );
      expect(violations.length).toBeGreaterThanOrEqual(1);
      expect(violations.some((v) => v.pattern.includes("execSync"))).toBe(true);
    });

    it("detects spawn/spawnSync", () => {
      const violations = scanSourceText(
        `spawn("bash", ["-c", "evil"]);`,
        "fake.ts",
      );
      expect(violations.length).toBeGreaterThanOrEqual(1);
    });

    it("detects process.env access", () => {
      const violations = scanSourceText(
        `const key = process.env.SECRET;`,
        "fake.ts",
      );
      expect(violations.length).toBeGreaterThanOrEqual(1);
      expect(violations.some((v) => v.pattern === "process.env")).toBe(true);
    });

    it("detects fs.writeFileSync", () => {
      const violations = scanSourceText(
        `fs.writeFileSync("/etc/hosts", "evil");`,
        "fake.ts",
      );
      expect(violations.length).toBeGreaterThanOrEqual(1);
    });

    it("detects fs.rmSync / fs.unlinkSync", () => {
      const v1 = scanSourceText(`fs.rmSync("/tmp/important");`, "fake.ts");
      const v2 = scanSourceText(`fs.unlinkSync("/tmp/important");`, "fake.ts");
      expect(v1.length).toBeGreaterThanOrEqual(1);
      expect(v2.length).toBeGreaterThanOrEqual(1);
    });

    it("detects dotenv import", () => {
      const violations = scanSourceText(
        `import "dotenv/config";`,
        "fake.ts",
      );
      expect(violations.length).toBeGreaterThanOrEqual(1);
    });

    it("returns empty for clean source", () => {
      const violations = scanSourceText(
        `import React from "react";\nconst x = 1 + 1;`,
        "clean.ts",
      );
      expect(violations).toHaveLength(0);
    });

    it("records file path, line number, and pattern label", () => {
      const text = "line1\nline2\nprocess.env.SECRET\nline4";
      const violations = scanSourceText(text, "my/file.ts");
      expect(violations.length).toBeGreaterThanOrEqual(1);
      const v = violations[0];
      expect(v.file).toBe("my/file.ts");
      expect(v.line).toBe(3);
      expect(v.pattern).toBe("process.env");
      expect(v.content).toContain("process.env.SECRET");
    });
  });

  describe("scanForForbiddenImports (integration — actual src/)", () => {
    it("returns ScanResult with violations array", () => {
      const result = scanForForbiddenImports();
      expect(result).toBeDefined();
      expect(Array.isArray(result.violations)).toBe(true);
    });

    it("does not flag main.tsx git execSync (allowlisted)", () => {
      const result = scanForForbiddenImports();
      const mainViolations = result.violations.filter(
        (v) => v.file === "main.tsx",
      );
      expect(mainViolations).toHaveLength(0);
    });

    it("no violations in source except allowlisted ones", () => {
      const result = scanForForbiddenImports();
      // 当前所有 .ts/.tsx 文件的 execSync 调用都应是 main.tsx 中被 allowlist 覆盖的 git 只读操作
      const unexpectedViolations = result.violations.filter(
        (v) => v.pattern.includes("exec") || v.pattern.includes("spawn"),
      );
      expect(unexpectedViolations).toHaveLength(0);
    });

    it("no .env access in source", () => {
      const result = scanForForbiddenImports();
      const envViolations = result.violations.filter(
        (v) => v.pattern.includes(".env") || v.pattern.includes("dotenv"),
      );
      expect(envViolations).toHaveLength(0);
    });

    it("non-allowlisted execSync would be caught", () => {
      // 直接测试 scanSourceText — allowlist 只在 scanForForbiddenImports 文件级生效
      const raw = scanSourceText(
        `execSync("rm -rf /");`,
        "some/other/file.ts",
      );
      expect(raw.length).toBeGreaterThanOrEqual(1);
    });
  });
});
