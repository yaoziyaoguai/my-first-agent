export function wireApp({ form, input, renderItems }) {
  const items = ["existing"];

  function render() {
    renderItems([...items]);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    items.push(input.value);
    input.value = "";
  });

  render();
}

if (typeof document !== "undefined") {
  const form = document.querySelector("#item-form");
  const input = document.querySelector("#item-name");
  const list = document.querySelector("#items");
  wireApp({
    form,
    input,
    renderItems(items) {
      list.replaceChildren(
        ...items.map((item) => {
          const row = document.createElement("li");
          row.textContent = item;
          return row;
        }),
      );
    },
  });
}
