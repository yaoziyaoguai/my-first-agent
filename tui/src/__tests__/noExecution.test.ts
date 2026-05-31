import { describe, it, expect } from "vitest";
import { scanForForbiddenImports } from "../data/noExecution";

describe("No-execution safety gate", () => {
  it("scanForForbiddenImports returns results object", () => {
    const result = scanForForbiddenImports();
    expect(result).toBeDefined();
    expect(Array.isArray(result.violations)).toBe(true);
  });

  it("no child_process imports in source", () => {
    const result = scanForForbiddenImports();
    const childProcessViolations = result.violations.filter(
      (v) => v.includes("child_process") || v.includes("exec") || v.includes("spawn"),
    );
    expect(childProcessViolations).toHaveLength(0);
  });

  it("no .env access in source", () => {
    const result = scanForForbiddenImports();
    const envViolations = result.violations.filter(
      (v) => v.includes(".env") || v.includes("dotenv"),
    );
    expect(envViolations).toHaveLength(0);
  });

  it("no fetch or axios in source", () => {
    const result = scanForForbiddenImports();
    const fetchViolations = result.violations.filter(
      (v) => v.includes("fetch") || v.includes("axios") || v.includes("node-fetch"),
    );
    expect(fetchViolations).toHaveLength(0);
  });

  it("no execSync or spawn in source", () => {
    const result = scanForForbiddenImports();
    const execViolations = result.violations.filter(
      (v) => v.includes("execSync") || v.includes("spawnSync"),
    );
    expect(execViolations).toHaveLength(0);
  });

  it("violations property is always an array", () => {
    const result = scanForForbiddenImports();
    expect(Array.isArray(result.violations)).toBe(true);
  });
});
