import assert from "node:assert/strict";
import test from "node:test";
import { pathToFileURL } from "node:url";

// D06 独立 grader 的冻结行为断言（位于 candidate 之外，产品不可改写）。
// candidate 路径经 D06_CANDIDATE 注入；candidate 自带 tests 不参与判定。
const candidate = process.env.D06_CANDIDATE;
if (!candidate) {
  throw new Error("D06_CANDIDATE must point at the candidate workspace");
}
const { wireApp } = await import(
  pathToFileURL(`${candidate}/web/app.mjs`).href
);

test("submitting an item immediately refreshes the visible list", () => {
  let submit;
  const rendered = [];
  const form = {
    addEventListener(name, handler) {
      assert.equal(name, "submit");
      submit = handler;
    },
  };
  const input = { value: "new item" };
  wireApp({ form, input, renderItems: (items) => rendered.push(items) });

  submit({ preventDefault() {} });

  assert.deepEqual(rendered, [["existing"], ["existing", "new item"]]);
  assert.equal(input.value, "");
});
