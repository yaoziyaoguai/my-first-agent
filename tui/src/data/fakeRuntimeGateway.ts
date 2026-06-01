/** Fake RuntimeGateway — M3 fake/local interaction MVP。
 *  不调用真实 API，不读取 .env，不导入 Python runtime。
 *  只作为 future core.chat() 的边界接口 placeholder。 */

export interface RuntimeMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
}

let _counter = 0;
function nextId(): string {
  _counter += 1;
  return `msg-${_counter}`;
}

const FAKE_RESPONSES: Record<string, string> = {
  hello: "Hello! I'm First Agent. How can I help you today?",
  hi: "Hi there! What would you like to work on?",
  help: "I can help you with:\n- Code exploration and analysis\n- Tool execution (fake/local mode)\n- Memory management\n- Multi-agent coordination\n\nThis is fake/local mode — no real runtime is connected.",
  status: "All systems nominal. Fake/local mode. No real agents connected.",
  memory: "Memory store: 3 entries (fake).\n- design/architecture: microservices pattern\n- bug/JIRA-123: fixed in v2.1.0\n- config/timeout: 30s default",
  tool: "[tool call placeholder] Tool execution not available in fake/local mode. M3 will add real tool pipeline via RuntimeGateway.",
  default: "I received your message. This is a fake/local response — no real agent runtime is connected yet. M3 will wire core.chat() through RuntimeGateway for real interaction.",
};

function pickResponse(input: string): string {
  const lower = input.toLowerCase().trim();
  for (const [key, response] of Object.entries(FAKE_RESPONSES)) {
    if (lower.includes(key)) return response;
  }
  return FAKE_RESPONSES.default;
}

/** Fake RuntimeGateway.send() — 返回 deterministic fake assistant 响应 */
export function fakeRuntimeSend(
  userInput: string,
  _agentId: string | null,
): RuntimeMessage {
  return {
    id: nextId(),
    role: "assistant",
    content: pickResponse(userInput),
    timestamp: Date.now(),
  };
}

/** 创建 user message */
export function makeUserMessage(content: string): RuntimeMessage {
  return {
    id: nextId(),
    role: "user",
    content,
    timestamp: Date.now(),
  };
}
