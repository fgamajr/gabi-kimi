const SERVICE_WORKER_PATH = "/sw.js";

export function registerAppServiceWorker() {
  if (!("serviceWorker" in navigator) || import.meta.env.DEV) return;

  window.addEventListener("load", () => {
    navigator.serviceWorker.register(SERVICE_WORKER_PATH).catch(() => undefined);
  });
}
