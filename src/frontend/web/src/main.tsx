import * as Sentry from "@sentry/react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import ErrorFallback from "./components/ErrorFallback";
import "./index.css";
import { registerAppServiceWorker } from "@/lib/pwa";

const dsn = import.meta.env.VITE_SENTRY_DSN_FRONTEND;
if (dsn) {
  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    tracesSampleRate: 0,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
  });
}

registerAppServiceWorker();
createRoot(document.getElementById("root")!).render(
  <Sentry.ErrorBoundary fallback={<ErrorFallback />}>
    <App />
  </Sentry.ErrorBoundary>
);
