import type { DogfoodResult } from "../types";

/** 从单个 dogfood JSON 对象中提取摘要信息 */
export function parseDogfoodResult(
  fileName: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  json: Record<string, any>,
): DogfoodResult {
  let pass = safeInt(json.pass);
  let fail = safeInt(json.fail);
  let concern = safeInt(json.concern);

  // 如果顶层计数不全，从 results 数组统计
  if (pass === 0 && fail === 0 && concern === 0 && Array.isArray(json.results)) {
    for (const item of json.results) {
      const v = item.verdict;
      if (v === "PASS") pass++;
      else if (v === "FAIL") fail++;
      else if (v === "CONCERN") concern++;
    }
  }

  return {
    fileName,
    pass,
    fail,
    concern,
    summary: typeof json.summary === "string" ? json.summary : "",
  };
}

function safeInt(val: unknown): number {
  if (typeof val === "number" && Number.isFinite(val)) return val;
  if (typeof val === "string") {
    const n = parseInt(val, 10);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}
