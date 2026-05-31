import { describe, it, expect } from "vitest";
import {
  createConfirmationRequest,
  confirmExecution,
  cancelExecution,
  dryRunExecution,
  needsDoubleConfirmation,
  buildExecutionCommand,
  EXECUTION_TIMEOUT_MS,
  CONFIRMATION_TIMEOUT_MS,
} from "../data/executionGate";
import type { CommandDefinition, SafetyLevel } from "../types";

const makeCmd = (
  safetyLevel: SafetyLevel,
  shellCommand?: string,
  riskNote?: string,
): CommandDefinition => ({
  id: "test-cmd",
  name: "Test Command",
  description: "A test command",
  category: "diagnostics",
  safetyLevel,
  requiresConfirmation: safetyLevel === "requires-confirmation",
  executableInPhase2: false,
  shellCommand,
  riskNote,
});

describe("executionGate", () => {
  describe("createConfirmationRequest", () => {
    it("creates request with command info", () => {
      const cmd = makeCmd("preview-only", "python main.py status");
      const req = createConfirmationRequest(cmd);
      expect(req.commandId).toBe("test-cmd");
      expect(req.shellCommand).toBe("python main.py status");
      expect(req.safetyLevel).toBe("preview-only");
    });

    it("sets single confirmation for preview-only commands", () => {
      const cmd = makeCmd("preview-only", "python main.py status");
      const req = createConfirmationRequest(cmd);
      expect(req.requiresDoubleConfirmation).toBe(false);
    });

    it("sets double confirmation for autorun command", () => {
      const autorunCmd: CommandDefinition = {
        id: "autorun",
        name: "AutoRun",
        description: "",
        category: "workflow",
        safetyLevel: "requires-confirmation",
        requiresConfirmation: true,
        executableInPhase2: false,
        shellCommand: "python main.py auto-run",
        riskNote: "高风险操作",
      };
      const req = createConfirmationRequest(autorunCmd);
      expect(req.requiresDoubleConfirmation).toBe(true);
    });

    it("sets single confirmation for non-autorun requires-confirmation commands", () => {
      const auditCmd: CommandDefinition = {
        id: "audit",
        name: "Audit",
        description: "",
        category: "diagnostics",
        safetyLevel: "requires-confirmation",
        requiresConfirmation: true,
        executableInPhase2: false,
        shellCommand: "python main.py audit",
        riskNote: "低风险只读审计",
      };
      const req = createConfirmationRequest(auditCmd);
      expect(req.requiresDoubleConfirmation).toBe(false);
    });
  });

  describe("confirmExecution", () => {
    it("returns confirmed status", () => {
      const cmd = makeCmd("preview-only", "python main.py status");
      const req = createConfirmationRequest(cmd);
      const result = confirmExecution(req);
      expect(result.status).toBe("confirmed");
      expect(result.commandId).toBe("test-cmd");
    });

    it("does not require double confirm text for single confirmation", () => {
      const cmd = makeCmd("preview-only", "python main.py status");
      const req = createConfirmationRequest(cmd);
      const result = confirmExecution(req);
      expect(result.needsDoubleConfirmText).toBe(false);
    });

    it("requires double confirm text for double confirmation", () => {
      const autorunCmd: CommandDefinition = {
        id: "autorun",
        name: "AutoRun",
        description: "",
        category: "workflow",
        safetyLevel: "requires-confirmation",
        requiresConfirmation: true,
        executableInPhase2: false,
        shellCommand: "python main.py auto-run",
        riskNote: "高风险",
      };
      const req = createConfirmationRequest(autorunCmd);
      const firstConfirm = confirmExecution(req);
      expect(firstConfirm.needsDoubleConfirmText).toBe(true);
      expect(firstConfirm.status).toBe("awaiting-double-confirm");
    });

    it("double confirm resolves to confirmed after 'yes'", () => {
      const autorunCmd: CommandDefinition = {
        id: "autorun",
        name: "AutoRun",
        description: "",
        category: "workflow",
        safetyLevel: "requires-confirmation",
        requiresConfirmation: true,
        executableInPhase2: false,
        shellCommand: "python main.py auto-run",
        riskNote: "高风险",
      };
      const req = createConfirmationRequest(autorunCmd);
      const firstConfirm = confirmExecution(req);
      const secondConfirm = confirmExecution(firstConfirm, "yes");
      expect(secondConfirm.status).toBe("confirmed");
    });

    it("double confirm with wrong text stays awaiting", () => {
      const autorunCmd: CommandDefinition = {
        id: "autorun",
        name: "AutoRun",
        description: "",
        category: "workflow",
        safetyLevel: "requires-confirmation",
        requiresConfirmation: true,
        executableInPhase2: false,
        shellCommand: "python main.py auto-run",
        riskNote: "高风险",
      };
      const req = createConfirmationRequest(autorunCmd);
      const firstConfirm = confirmExecution(req);
      const secondConfirm = confirmExecution(firstConfirm, "no");
      expect(secondConfirm.status).toBe("awaiting-double-confirm");
    });
  });

  describe("cancelExecution", () => {
    it("returns cancelled status", () => {
      const cmd = makeCmd("preview-only", "python main.py status");
      const result = cancelExecution("test-cmd");
      expect(result.status).toBe("cancelled");
      expect(result.commandId).toBe("test-cmd");
    });
  });

  describe("dryRunExecution", () => {
    it("returns dry-run status with would-execute info", () => {
      const cmd = makeCmd("preview-only", "python main.py status");
      const result = dryRunExecution(cmd);
      expect(result.status).toBe("dry-run");
      expect(result.wouldExecute).toBe("python main.py status");
      expect(result.actuallyExecuted).toBe(false);
    });

    it("shows dry-run for autorun commands", () => {
      const cmd = makeCmd("requires-confirmation", "python main.py auto-run", "高风险");
      const result = dryRunExecution(cmd);
      expect(result.status).toBe("dry-run");
      expect(result.actuallyExecuted).toBe(false);
    });
  });

  describe("needsDoubleConfirmation", () => {
    it("returns true for autorun command", () => {
      expect(needsDoubleConfirmation("autorun")).toBe(true);
    });

    it("returns false for status command", () => {
      expect(needsDoubleConfirmation("status")).toBe(false);
    });
  });

  describe("buildExecutionCommand", () => {
    it("builds command for allowed whitelist entry", () => {
      const cmd = makeCmd("preview-only", "python main.py status");
      const result = buildExecutionCommand(cmd);
      expect(result.command).toBe("python main.py status");
    });

    it("throws for commands without shellCommand", () => {
      const cmd = makeCmd("preview-only", undefined);
      expect(() => buildExecutionCommand(cmd)).toThrow();
    });
  });

  describe("timeout constants", () => {
    it("EXECUTION_TIMEOUT_MS is 60000", () => {
      expect(EXECUTION_TIMEOUT_MS).toBe(60_000);
    });

    it("CONFIRMATION_TIMEOUT_MS is 30000", () => {
      expect(CONFIRMATION_TIMEOUT_MS).toBe(30_000);
    });
  });
});
