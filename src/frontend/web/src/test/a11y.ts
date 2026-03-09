import { computeAccessibleName } from "dom-accessibility-api";
import { expect } from "vitest";

function describeElement(element: Element) {
  const role = element.getAttribute("role");
  const id = element.getAttribute("id");
  const type = element.getAttribute("type");

  return [
    element.tagName.toLowerCase(),
    role ? `role=${role}` : null,
    type ? `type=${type}` : null,
    id ? `id=${id}` : null,
  ]
    .filter(Boolean)
    .join(" ");
}

export function expectNamedInteractiveElements(container: HTMLElement) {
  const interactive = Array.from(
    container.querySelectorAll(
      'a[href], button, input:not([type="hidden"]), textarea, select, [role="button"], [role="combobox"]',
    ),
  );

  const unnamed = interactive
    .map((element) => ({
      description: describeElement(element),
      name: computeAccessibleName(element).trim(),
    }))
    .filter(({ name }) => name.length === 0)
    .map(({ description }) => description);

  expect(unnamed).toEqual([]);
}
