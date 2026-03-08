import React, { useState } from "react";
import { Icons } from "@/components/Icons";

interface AccessKeyPromptProps {
  title?: string;
  description?: string;
  submitLabel?: string;
  error?: string | null;
  pending?: boolean;
  onSubmit: (accessKey: string) => Promise<void> | void;
}

export const AccessKeyPrompt: React.FC<AccessKeyPromptProps> = ({
  title = "Acesso protegido",
  description = "Insira a chave de acesso para abrir este conteúdo protegido.",
  submitLabel = "Desbloquear",
  error,
  pending = false,
  onSubmit,
}) => {
  const [accessKey, setAccessKey] = useState("");

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSubmit(accessKey);
  };

  return (
    <div className="min-h-screen bg-background px-4 py-10">
      <div className="mx-auto max-w-lg rounded-[2rem] border border-white/10 bg-[rgba(12,14,24,0.92)] p-6 shadow-[0_30px_90px_rgba(0,0,0,0.24)] backdrop-blur-xl md:p-8">
        <div className="mb-6 flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04] text-primary">
          <Icons.lock className="h-5 w-5" />
        </div>
        <h1 className="font-editorial text-3xl text-foreground">{title}</h1>
        <p className="mt-3 text-sm leading-6 text-text-secondary">{description}</p>

        <form className="mt-8 space-y-4" onSubmit={handleSubmit}>
          <label className="block space-y-2">
            <span className="text-xs uppercase tracking-[0.24em] text-text-tertiary">Access Key</span>
            <input
              type="password"
              value={accessKey}
              onChange={(event) => setAccessKey(event.target.value)}
              autoComplete="current-password"
              className="h-12 w-full rounded-2xl border border-white/10 bg-white/[0.03] px-4 text-sm text-foreground outline-none transition-colors focus:border-primary/35"
              placeholder="Cole a chave Bearer do ambiente"
              disabled={pending}
            />
          </label>

          {error ? (
            <div className="rounded-2xl border border-[rgba(215,130,119,0.28)] bg-[rgba(215,130,119,0.08)] px-4 py-3 text-sm text-[rgb(237,190,183)]">
              {error}
            </div>
          ) : null}

          <button
            type="submit"
            disabled={pending || !accessKey.trim()}
            className="flex h-12 w-full items-center justify-center rounded-2xl border border-primary/20 bg-primary/14 text-sm font-medium text-primary transition-colors hover:bg-primary/18 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending ? "Validando..." : submitLabel}
          </button>
        </form>
      </div>
    </div>
  );
};
