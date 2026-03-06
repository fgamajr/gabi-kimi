import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app.jsx";

const root = createRoot(document.getElementById("app-root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/dist/sw.js").catch(() => {});
  });
}
