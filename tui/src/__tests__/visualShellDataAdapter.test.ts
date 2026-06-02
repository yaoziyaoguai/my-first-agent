/**
 * Slice B — Data adapter tests.
 * Verifies safe data → view model conversion, provenance labels, and safety guards.
 */
import { describe, test, expect } from "vitest";
import {
  buildVisualShellViewModel,
  buildDefaultViewModel,
} from "../data/visualShellDataAdapter";
import type { SafeDataSources } from "../data/visualShellDataAdapter";
import {
  SAFE_RUNTIME_DECISION,
  SAFE_MCP_STATUS,
  SAFE_TOOL_SUMMARY,
  SAFE_EVENTS,
  SAFE_MEMORY_CKPT,
  SAFE_PROVIDER_LABEL,
  SAFE_RUNTIME_STATUS,
  SAFE_BOTTOM_STATUS,
  SAFE_TOP_BAR,
  SAFE_WORKSPACES,
  SAFE_LENSES,
  SAFE_SESSIONS,
  SAFE_MESSAGES,
  SAFE_TOOL_CALLS,
  SAFE_PENDING_ACTIONS,
  SAFE_TABLE_RESULTS,
  SAFE_EVIDENCE_ITEMS,
  SAFE_SKILL_EVIDENCE,
} from "../data/safeDataSources";
import type { ViewLens } from "../data/visualShellTypes";

function makeSafeSources(
  overrides?: Partial<SafeDataSources>,
): SafeDataSources {
  return {
    lens: "Agent" as ViewLens,
    runtimeDecision: SAFE_RUNTIME_DECISION,
    mcpStatus: SAFE_MCP_STATUS,
    toolSummary: SAFE_TOOL_SUMMARY,
    events: SAFE_EVENTS,
    memoryCkpt: SAFE_MEMORY_CKPT,
    evidenceItemCount: SAFE_EVIDENCE_ITEMS.length,
    evidenceItems: SAFE_EVIDENCE_ITEMS,
    providerLabel: SAFE_PROVIDER_LABEL,
    runtimeStatus: SAFE_RUNTIME_STATUS,
    bottomStatus: SAFE_BOTTOM_STATUS,
    topBar: SAFE_TOP_BAR,
    workspaces: SAFE_WORKSPACES,
    lenses: SAFE_LENSES,
    sessions: SAFE_SESSIONS,
    messages: SAFE_MESSAGES,
    toolCalls: SAFE_TOOL_CALLS,
    pendingActions: SAFE_PENDING_ACTIONS,
    tableResults: SAFE_TABLE_RESULTS,
    skillEvidence: SAFE_SKILL_EVIDENCE,
    ...overrides,
  };
}

// ── Core adapter tests ──

describe("visualShellDataAdapter", () => {
  test("builds view model from safe data sources", () => {
    const sources = makeSafeSources();
    const vm = buildVisualShellViewModel(sources);

    expect(vm.fixture).toBeDefined();
    expect(vm.fixture.topBar.productName).toBe("First Agent TUI");
    expect(vm.fixture.inspector.runtimeDecision.mode).toBe("ACT");
    expect(vm.fixture.inspector.mcpBridge.discoverCount).toBe(14);
    expect(vm.fixture.inspector.toolSummary).toHaveLength(5);
    expect(vm.fixture.inspector.evidence.itemCount).toBe(8);
  });

  test("provenance labels are correct", () => {
    const sources = makeSafeSources();
    const vm = buildVisualShellViewModel(sources);

    expect(vm.provenance.runtimeDecision).toBe("fake/local");
    expect(vm.provenance.mcpStatus).toBe("local-mcp-smoke");
    expect(vm.provenance.evidence).toBe("evidence-derived");
    expect(vm.provenance.skillEvidence).toBe("evidence-derived");
    expect(vm.provenance.messages).toBe("fake/local");
  });

  test("topBar reflects safe provider label, not fake/local", () => {
    const sources = makeSafeSources();
    const vm = buildVisualShellViewModel(sources);

    expect(vm.fixture.topBar.provider).toContain("anthropic_compatible");
    expect(vm.fixture.topBar.isFake).toBe(false);
  });

  test("MCP status shows local smoke data", () => {
    const sources = makeSafeSources();
    const vm = buildVisualShellViewModel(sources);

    expect(vm.fixture.inspector.mcpBridge.status).toBe("partial");
    expect(vm.fixture.inspector.mcpBridge.discoverCount).toBe(14);
    expect(vm.fixture.inspector.mcpBridge.invokeReady).toBe(true);
  });

  test("empty overrides work", () => {
    const sources = makeSafeSources({
      messages: [],
      toolCalls: [],
      pendingActions: [],
      tableResults: [],
    });
    const vm = buildVisualShellViewModel(sources);

    expect(vm.fixture.tableResults).toBeUndefined();
    expect(vm.fixture.messages).toHaveLength(0);
    expect(vm.fixture.toolCalls).toHaveLength(0);
  });

  test("table results present when data provided", () => {
    const sources = makeSafeSources({
      tableResults: [
        {
          headers: ["Col1", "Col2"],
          rows: [["a", "b"]],
        },
      ],
    });
    const vm = buildVisualShellViewModel(sources);

    expect(vm.fixture.tableResults).toBeDefined();
    expect(vm.fixture.tableResults).toHaveLength(1);
  });
});

// ── Edge cases ──

describe("visualShellDataAdapter edge cases", () => {
  test("buildDefaultViewModel returns valid fixture", () => {
    const vm = buildDefaultViewModel();

    expect(vm.fixture).toBeDefined();
    expect(vm.fixture.topBar.productName).toBe("First Agent TUI");
    expect(vm.fixture.inspector.runtimeDecision.status).toBe("partial");
    expect(vm.fixture.inspector.mcpBridge.status).toBe("disabled");
    expect(vm.fixture.messages).toHaveLength(0);
    expect(vm.fixture.toolCalls).toHaveLength(0);
  });

  test("buildDefaultViewModel with overrides", () => {
    const vm = buildDefaultViewModel({
      lens: "Evidence" as ViewLens,
      evidenceItemCount: 5,
      providerLabel: "custom",
      topBar: {
        productName: "First Agent TUI",
        mode: "ACT",
        lens: "Agent" as ViewLens,
        provider: "custom",
        isFake: true,
      },
    });

    expect(vm.fixture.bottomStatus.lens).toBe("Agent"); // lens not wired into bottomStatus via defaults
    expect(vm.fixture.inspector.evidence.itemCount).toBe(5);
    expect(vm.fixture.topBar.provider).toBe("custom");
    expect(vm.fixture.topBar.isFake).toBe(true);
  });

  test("fixture label is not product-ready", () => {
    const sources = makeSafeSources();
    const vm = buildVisualShellViewModel(sources);

    expect(vm.fixture._label).toContain("not product-ready");
    expect(vm.fixture._label).not.toContain("production");
    // "product-ready" substring exists inside "not product-ready" — verify it's negated
    expect(vm.fixture._label).toContain("not product-ready");
    expect(vm.fixture._label).not.toMatch(/^\s*product-ready\s*$/);
    expect(vm.fixture._label).not.toContain("production-ready");
  });
});

// ── Safety guard tests ──

describe("visualShellDataAdapter safety guards", () => {
  test("no real API key in any data", () => {
    const sources = makeSafeSources();
    const vm = buildVisualShellViewModel(sources);
    const json = JSON.stringify(vm);

    expect(json).not.toContain("sk-");
    expect(json).not.toContain("api_key");
    expect(json).not.toContain("Bearer");
  });

  test("no .env reference", () => {
    const sources = makeSafeSources();
    const vm = buildVisualShellViewModel(sources);
    const json = JSON.stringify(vm);

    expect(json).not.toContain(".env");
  });

  test("no product-ready claim", () => {
    const sources = makeSafeSources();
    const vm = buildVisualShellViewModel(sources);
    const json = JSON.stringify(vm);

    expect(json).not.toMatch(/"product-ready"/i);
    expect(json).not.toMatch(/"production-ready"/i);
  });

  test("no Dashboard/AutoRun resurrection", () => {
    const sources = makeSafeSources();
    const vm = buildVisualShellViewModel(sources);
    const json = JSON.stringify(vm);

    expect(json).not.toContain("Dashboard");
    expect(json).not.toContain("AutoRun");
    expect(json).not.toContain("Project Operations");
  });

  test("MCP status not labeled as production", () => {
    const sources = makeSafeSources();
    const vm = buildVisualShellViewModel(sources);

    expect(vm.provenance.mcpStatus).toBe("local-mcp-smoke");
    expect(vm.provenance.mcpStatus).not.toBe("production");
  });

  test("evidence not labeled as live", () => {
    const sources = makeSafeSources();
    const vm = buildVisualShellViewModel(sources);

    expect(vm.provenance.evidence).toBe("evidence-derived");
    expect(vm.provenance.evidence).not.toBe("live");
  });
});
