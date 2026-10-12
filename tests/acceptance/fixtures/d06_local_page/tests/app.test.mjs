import assert from "node:assert/strict";
import test from "node:test";

import { wireApp } from "../web/app.mjs";

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
