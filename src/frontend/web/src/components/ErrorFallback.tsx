/** Fallback UI when Sentry.ErrorBoundary catches a render error. */
export default function ErrorFallback() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background p-6 text-foreground">
      <p className="text-center text-lg">Algo deu errado. Tente recarregar a página.</p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="rounded-lg bg-primary px-4 py-2 text-primary-foreground hover:opacity-90"
      >
        Recarregar
      </button>
    </div>
  );
}
