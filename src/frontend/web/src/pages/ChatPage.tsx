import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AccessKeyPrompt } from "@/components/AccessKeyPrompt";
import { Icons } from "@/components/Icons";
import { ApiAuthError, createAccessSession, getSessionStatus } from "@/lib/auth";
import { getSearchExamples, sendChat, streamChat } from "@/lib/api";
import type { ChatMessage, SearchExample, SearchResult } from "@/lib/api";
import { navigateToDocument } from "@/lib/navigation";

interface ChatBubble extends ChatMessage {
  id: string;
  meta?: {
    model?: string;
    cache?: string;
    sourceCount?: number;
  };
  sources?: SearchResult[];
}

const INITIAL_ASSISTANT_MESSAGE =
  "Posso ajudar a localizar atos, resumir buscas e explicar como consultar o DOU. Peça algo como `portarias da ANVISA de 2024`, `explique a lei 9.394` ou `quais decretos regulamentam esta norma?`.";

const FALLBACK_SUGGESTIONS = [
  "últimas portarias da ANVISA",
  "lei 9.394/96",
  "editais de licitação do3 desta semana",
  "decretos da presidência sobre educação",
];

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderInlineMarkdown(value: string) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
}

function MessageBody({ content }: { content: string }) {
  const blocks = content.split(/\n\n+/).filter(Boolean);
  return (
    <div className="space-y-3 text-sm leading-7 text-foreground">
      {blocks.map((block, index) => {
        const lines = block.split("\n").filter(Boolean);
        const isList = lines.every((line) => /^[-•]\s+/.test(line.trim()));
        if (isList) {
          return (
            <ul key={index} className="space-y-2 pl-5 text-text-secondary">
              {lines.map((line, itemIndex) => (
                <li
                  key={itemIndex}
                  className="list-disc"
                  dangerouslySetInnerHTML={{ __html: renderInlineMarkdown(line.replace(/^[-•]\s+/, "")) }}
                />
              ))}
            </ul>
          );
        }
        return (
          <p
            key={index}
            className="whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ __html: renderInlineMarkdown(block) }}
          />
        );
      })}
    </div>
  );
}

function formatMetaDate(value?: string) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleDateString("pt-BR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return value;
  }
}

const ChatPage: React.FC = () => {
  const navigate = useNavigate();
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [messages, setMessages] = useState<ChatBubble[]>([
    { id: "assistant-initial", role: "assistant", content: INITIAL_ASSISTANT_MESSAGE },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [needsAccess, setNeedsAccess] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authPending, setAuthPending] = useState(false);
  const [examples, setExamples] = useState<SearchExample[]>([]);

  useEffect(() => {
    getSessionStatus()
      .then(() => setNeedsAccess(false))
      .catch((error) => {
        if (error instanceof ApiAuthError) {
          setNeedsAccess(true);
          return;
        }
      });
    getSearchExamples()
      .then((items) => setExamples(items.slice(0, 4)))
      .catch(() => setExamples([]));
  }, []);

  useEffect(() => {
    const node = viewportRef.current;
    if (!node) return;
    node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
  }, [messages, streaming]);

  const quickReplies = useMemo(
    () => (examples.length > 0 ? examples.map((item) => item.query) : FALLBACK_SUGGESTIONS),
    [examples]
  );

  const submitAccessKey = async (accessKey: string) => {
    setAuthPending(true);
    setAuthError(null);
    try {
      await createAccessSession(accessKey);
      setNeedsAccess(false);
    } catch (error) {
      if (error instanceof ApiAuthError) {
        setAuthError("Chave inválida. Confirme o token Bearer configurado no ambiente.");
      } else {
        setAuthError("Não foi possível validar a chave agora.");
      }
    } finally {
      setAuthPending(false);
    }
  };

  const sendMessage = async (seed?: string) => {
    const message = (seed ?? input).trim();
    if (!message || streaming) return;

    const baseHistory: ChatMessage[] = messages.map(({ role, content }) => ({ role, content }));
    const userMessage: ChatBubble = {
      id: `user-${Date.now()}`,
      role: "user",
      content: message,
    };
    const assistantId = `assistant-${Date.now()}`;
    const assistantPlaceholder: ChatBubble = {
      id: assistantId,
      role: "assistant",
      content: "",
      meta: {},
    };

    setInput("");
    setStreaming(true);
    setMessages((current) => [...current, userMessage, assistantPlaceholder]);

    try {
      await streamChat(message, baseHistory, {
        onMeta: (meta) => {
          setMessages((current) =>
            current.map((item) =>
              item.id === assistantId
                ? {
                    ...item,
                    meta: {
                      model: meta.model,
                      cache: meta.cache,
                      sourceCount: meta.source_count,
                    },
                  }
                : item
            )
          );
        },
        onDelta: (chunk) => {
          setMessages((current) =>
            current.map((item) =>
              item.id === assistantId ? { ...item, content: `${item.content}${chunk}` } : item
            )
          );
        },
        onDone: (payload) => {
          setMessages((current) =>
            current.map((item) =>
              item.id === assistantId
                ? {
                    ...item,
                    content: payload.reply,
                    meta: {
                      model: payload.model,
                      cache: payload.cache,
                      sourceCount: payload.sources?.length,
                    },
                    sources: payload.sources,
                  }
                : item
            )
          );
        },
        onError: (detail) => {
          setMessages((current) =>
            current.map((item) =>
              item.id === assistantId
                ? { ...item, content: `Falha no stream: ${detail}`, meta: { model: "erro" } }
                : item
            )
          );
        },
      });
    } catch (error) {
      if (error instanceof ApiAuthError) {
        setNeedsAccess(true);
        setMessages((current) => current.filter((item) => item.id !== assistantId));
        return;
      }
      try {
        const payload = await sendChat(message, baseHistory);
        setMessages((current) =>
          current.map((item) =>
            item.id === assistantId
              ? {
                  ...item,
                  content: payload.reply,
                  meta: {
                    model: payload.model,
                    cache: payload.cache,
                    sourceCount: payload.sources?.length,
                  },
                  sources: payload.sources,
                }
              : item
          )
        );
      } catch (fallbackError) {
        setMessages((current) =>
          current.map((item) =>
            item.id === assistantId
              ? { ...item, content: "Não foi possível concluir a resposta agora.", meta: { model: "erro" } }
              : item
          )
        );
        if (fallbackError instanceof ApiAuthError) {
          setNeedsAccess(true);
        }
      }
    } finally {
      setStreaming(false);
    }
  };

  if (needsAccess) {
    return (
      <AccessKeyPrompt
        title="Chat protegido"
        description="Insira a chave de acesso para usar o chat operacional da GABI com streaming e contexto do corpus."
        submitLabel="Abrir chat"
        error={authError}
        pending={authPending}
        onSubmit={submitAccessKey}
      />
    );
  }

  return (
    <div className="min-h-screen bg-background px-4 pb-24 pt-6 md:px-8 md:pb-8">
      <div className="mx-auto grid max-w-7xl gap-5 lg:grid-cols-[280px,minmax(0,1fr)]">
        <aside className="reader-surface rounded-[28px] px-4 py-5 sm:px-5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-tertiary">Chat operacional</p>
          <h1 className="mt-3 font-editorial text-3xl leading-tight text-foreground">GABI conversa com o corpus</h1>
          <p className="mt-3 text-sm leading-6 text-text-secondary">
            Use o chat para transformar busca em diálogo, com resposta progressiva, contexto normativo e sugestões acionáveis.
          </p>

          <div className="mt-6 space-y-3">
            {quickReplies.map((suggestion) => (
              <button
                key={suggestion}
                onClick={() => void sendMessage(suggestion)}
                className="w-full rounded-[20px] border border-white/8 bg-white/[0.03] px-4 py-3 text-left text-sm text-text-secondary transition-colors hover:bg-white/[0.05] hover:text-foreground focus-ring"
              >
                {suggestion}
              </button>
            ))}
          </div>

          <div className="mt-6 rounded-[22px] border border-white/8 bg-black/10 px-4 py-4">
            <p className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary">Fluxo</p>
            <div className="mt-3 space-y-2 text-sm text-text-secondary">
              <p>1. interpreta sua consulta</p>
              <p>2. recupera atos e trechos relevantes</p>
              <p>3. responde com stream e fontes clicáveis</p>
            </div>
          </div>
        </aside>

        <section className="reader-surface flex min-h-[72vh] flex-col overflow-hidden rounded-[30px]">
          <header className="border-b border-white/8 px-4 py-4 sm:px-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.18em] text-text-tertiary">Assistente</p>
                <p className="mt-2 font-editorial text-2xl text-foreground">Conversa guiada por busca, não por palpite</p>
              </div>
              <div className="rounded-full border border-white/8 bg-white/[0.03] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-tertiary">
                {streaming ? "Transmitindo" : "Pronto"}
              </div>
            </div>
          </header>

          <div ref={viewportRef} className="flex-1 space-y-4 overflow-y-auto px-4 py-5 sm:px-6">
            {messages.map((message) => {
              const isAssistant = message.role === "assistant";
              const isEmptyStreamingBubble = streaming && isAssistant && !message.content;
              return (
                <div key={message.id} className={`flex ${isAssistant ? "justify-start" : "justify-end"}`}>
                  <div
                    className={`max-w-3xl rounded-[24px] border px-4 py-4 sm:px-5 ${
                      isAssistant
                        ? "border-white/8 bg-[linear-gradient(180deg,rgba(18,20,32,0.92),rgba(10,12,22,0.96))]"
                        : "border-primary/20 bg-primary/12"
                    }`}
                  >
                    <div className="mb-3 flex items-center gap-3">
                      <div
                        className={`flex h-9 w-9 items-center justify-center rounded-2xl border ${
                          isAssistant
                            ? "border-white/10 bg-white/[0.04] text-primary"
                            : "border-primary/15 bg-primary/15 text-primary"
                        }`}
                      >
                        {isAssistant ? <Icons.chat className="h-4 w-4" /> : <Icons.search className="h-4 w-4" />}
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-foreground">{isAssistant ? "GABI" : "Você"}</p>
                        {message.meta?.model || message.meta?.cache ? (
                          <p className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary">
                            {[
                              message.meta.model,
                              message.meta.cache === "hit" ? "cache" : null,
                              message.meta.sourceCount ? `${message.meta.sourceCount} fontes` : null,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </p>
                        ) : null}
                      </div>
                    </div>

                    {isEmptyStreamingBubble ? (
                      <div className="flex items-center gap-2 text-text-secondary">
                        <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-primary/60" />
                        <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-primary/40 [animation-delay:120ms]" />
                        <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-primary/30 [animation-delay:240ms]" />
                      </div>
                    ) : (
                      <div className="space-y-4">
                        <MessageBody content={message.content} />

                        {isAssistant && message.sources && message.sources.length > 0 ? (
                          <div className="space-y-3 rounded-[20px] border border-white/8 bg-black/10 p-3">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-tertiary">
                              Fontes recuperadas
                            </p>
                            <div className="space-y-2.5">
                              {message.sources.slice(0, 4).map((source) => (
                                <button
                                  key={`${message.id}-${source.id}`}
                                  type="button"
                                  onClick={() => navigateToDocument(navigate, source.id, "chat-rag")}
                                  className="w-full rounded-[18px] border border-white/8 bg-white/[0.03] px-3 py-3 text-left transition-colors hover:bg-white/[0.05] focus-ring"
                                >
                                  <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.14em] text-text-tertiary">
                                    {source.section ? <span>{source.section.toUpperCase()}</span> : null}
                                    {source.art_type ? <span>{source.art_type}</span> : null}
                                    {source.pub_date ? <span>{formatMetaDate(source.pub_date)}</span> : null}
                                  </div>
                                  <p className="mt-1 text-sm font-semibold text-foreground">{source.title}</p>
                                  {source.issuing_organ ? (
                                    <p className="mt-1 text-xs uppercase tracking-[0.14em] text-text-tertiary">
                                      {source.issuing_organ}
                                    </p>
                                  ) : null}
                                  {source.snippet ? (
                                    <p className="mt-2 line-clamp-3 text-sm leading-6 text-text-secondary">
                                      {source.snippet}
                                    </p>
                                  ) : null}
                                </button>
                              ))}
                            </div>
                          </div>
                        ) : null}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <footer className="border-t border-white/8 px-4 py-4 sm:px-6">
            <div className="mb-3 flex flex-wrap gap-2">
              {quickReplies.slice(0, 3).map((suggestion) => (
                <button
                  key={suggestion}
                  onClick={() => void sendMessage(suggestion)}
                  className="rounded-full border border-white/8 px-3 py-1.5 text-xs text-text-secondary transition-colors hover:bg-white/[0.05] hover:text-foreground focus-ring"
                >
                  {suggestion}
                </button>
              ))}
            </div>

            <div className="rounded-[24px] border border-white/8 bg-black/10 p-2">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void sendMessage();
                  }
                }}
                placeholder="Pergunte sobre uma norma, um órgão ou uma busca no DOU…"
                className="min-h-[112px] w-full resize-none bg-transparent px-3 py-3 text-sm text-foreground outline-none placeholder:text-text-tertiary"
              />
              <div className="flex items-center justify-between gap-3 px-2 pb-2">
                <p className="text-xs text-text-tertiary">Enter envia · Shift+Enter quebra linha</p>
                <button
                  onClick={() => void sendMessage()}
                  disabled={streaming || !input.trim()}
                  className="inline-flex min-h-[44px] items-center gap-2 rounded-[18px] border border-primary/20 bg-primary/12 px-4 text-sm font-medium text-primary transition-colors hover:bg-primary/18 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Icons.chevronRight className="h-4 w-4" />
                  Enviar
                </button>
              </div>
            </div>
          </footer>
        </section>
      </div>
    </div>
  );
};

export default ChatPage;
