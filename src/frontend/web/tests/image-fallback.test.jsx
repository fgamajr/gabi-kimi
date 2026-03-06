import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { ImageAsset } from "../src/document-renderer.jsx";

function installDom() {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/",
  });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: dom.window.navigator,
  });
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  globalThis.Node = dom.window.Node;
  globalThis.DOMParser = dom.window.DOMParser;
  globalThis.HTMLElement = dom.window.HTMLElement;
  return dom;
}

test("ImageAsset renders fallback after load error", async () => {
  const dom = installDom();
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(
      <ImageAsset
        doc={{ publication_date: "2002-02-14", section: "do2", page_number: 2 }}
        image={{
          media_name: "tabela1",
          blob_url: "/api/media/doc/tabela1",
          status: "available",
          context_hint: "table",
          fallback_text: "Tabela disponível apenas no documento original",
          original_url: "https://www.in.gov.br/imagens/2002/0214_tabela1.gif",
        }}
      />,
    );
  });

  const img = container.querySelector("img");
  assert.ok(img, "expected rendered image before error");

  await act(async () => {
    img.dispatchEvent(new dom.window.Event("error"));
  });

  assert.match(container.textContent || "", /Imagem indisponível/u);
  assert.match(container.textContent || "", /Tabela disponível apenas no documento original/u);
  assert.equal(container.querySelector("img"), null);

  await act(async () => {
    root.unmount();
  });
  dom.window.close();
});
