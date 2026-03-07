import React from "react";
import { createRoot } from "react-dom/client";
import { JSONUIProvider, Renderer, defineRegistry } from "@json-render/react";
import { useJsonRenderApp } from "@json-render/mcp/app";
import { catalog } from "./catalog.mjs";

const palette = {
  bg: "#0f1220",
  surface: "#171b2e",
  surfaceMuted: "#121629",
  border: "#2a3357",
  text: "#edf2ff",
  textMuted: "#a0adcf",
  accent: "#7c5cfc",
  success: "#33c28a",
  warning: "#f3b63f",
  danger: "#ff7d73",
};

function toneColors(tone) {
  switch (tone) {
    case "accent":
      return { background: "rgba(124,92,252,0.16)", color: palette.accent, borderColor: "rgba(124,92,252,0.28)" };
    case "success":
      return { background: "rgba(51,194,138,0.16)", color: palette.success, borderColor: "rgba(51,194,138,0.28)" };
    case "warning":
      return { background: "rgba(243,182,63,0.16)", color: palette.warning, borderColor: "rgba(243,182,63,0.28)" };
    case "danger":
      return { background: "rgba(255,125,115,0.16)", color: palette.danger, borderColor: "rgba(255,125,115,0.28)" };
    case "muted":
      return { background: palette.surfaceMuted, color: palette.textMuted, borderColor: palette.border };
    default:
      return { background: palette.surface, color: palette.text, borderColor: palette.border };
  }
}

const alignMap = { start: "flex-start", center: "center", end: "flex-end", stretch: "stretch" };
const justifyMap = { start: "flex-start", center: "center", end: "flex-end", between: "space-between" };

const { registry } = defineRegistry(catalog, {
  components: {
    Stack: ({ props, children }) => (
      <div
        style={{
          display: "flex",
          flexDirection: props.direction === "horizontal" ? "row" : "column",
          gap: `${props.gap ?? 12}px`,
          padding: props.padding ? `${props.padding}px` : undefined,
          alignItems: alignMap[props.align ?? "stretch"],
          justifyContent: justifyMap[props.justify ?? "start"],
          width: "100%",
        }}
      >
        {children}
      </div>
    ),
    Grid: ({ props, children }) => (
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${props.columns}, minmax(0, 1fr))`,
          gap: `${props.gap ?? 12}px`,
          width: "100%",
        }}
      >
        {children}
      </div>
    ),
    Card: ({ props, children }) => {
      const tone = toneColors(props.tone);
      return (
        <section
          style={{
            width: "100%",
            borderRadius: "16px",
            border: `1px solid ${tone.borderColor}`,
            background: tone.background,
            color: palette.text,
            padding: "16px",
            boxShadow: "0 10px 28px rgba(0,0,0,0.18)",
          }}
        >
          {props.title ? <div style={{ fontSize: "15px", fontWeight: 700, marginBottom: props.subtitle ? 4 : 12 }}>{props.title}</div> : null}
          {props.subtitle ? (
            <div style={{ fontSize: "13px", color: palette.textMuted, marginBottom: 12, lineHeight: 1.5 }}>{props.subtitle}</div>
          ) : null}
          {children}
        </section>
      );
    },
    Heading: ({ props }) => {
      const Tag = `h${props.level ?? 2}`;
      const sizes = { 1: "28px", 2: "22px", 3: "18px", 4: "15px" };
      return (
        <Tag
          style={{
            margin: 0,
            color: palette.text,
            fontSize: sizes[props.level ?? 2],
            lineHeight: 1.2,
            fontWeight: 800,
            letterSpacing: "-0.02em",
          }}
        >
          {props.text}
        </Tag>
      );
    },
    Text: ({ props }) => {
      const variant = props.variant ?? "body";
      const styles = {
        body: { fontSize: "14px", color: palette.text, lineHeight: 1.65 },
        muted: { fontSize: "13px", color: palette.textMuted, lineHeight: 1.6 },
        small: { fontSize: "12px", color: palette.textMuted, lineHeight: 1.5 },
        lead: { fontSize: "16px", color: palette.text, lineHeight: 1.7, fontWeight: 500 },
        code: {
          fontSize: "12px",
          color: "#d8defa",
          lineHeight: 1.5,
          background: "rgba(255,255,255,0.04)",
          border: `1px solid ${palette.border}`,
          borderRadius: "8px",
          padding: "10px 12px",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        },
      };
      return <p style={{ margin: 0, ...styles[variant] }}>{props.text}</p>;
    },
    Badge: ({ props }) => {
      const tone = toneColors(props.tone);
      return (
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
            padding: "6px 10px",
            borderRadius: "999px",
            border: `1px solid ${tone.borderColor}`,
            background: tone.background,
            color: tone.color,
            fontSize: "12px",
            fontWeight: 700,
            lineHeight: 1,
          }}
        >
          {props.text}
        </span>
      );
    },
    Divider: ({ props }) => (
      <div style={{ display: "flex", alignItems: "center", gap: "10px", width: "100%" }}>
        <div style={{ height: 1, flex: 1, background: palette.border }} />
        {props.label ? <span style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.08em", color: palette.textMuted }}>{props.label}</span> : null}
        {props.label ? <div style={{ height: 1, flex: 1, background: palette.border }} /> : null}
      </div>
    ),
    Button: ({ props }) => {
      const tone = toneColors(props.tone);
      const shared = {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "40px",
        padding: "0 14px",
        borderRadius: "12px",
        border: `1px solid ${tone.borderColor}`,
        background: tone.background,
        color: tone.color,
        fontSize: "13px",
        fontWeight: 700,
        textDecoration: "none",
      };
      return props.href ? (
        <a href={props.href} target="_blank" rel="noreferrer" style={shared}>
          {props.text}
        </a>
      ) : (
        <button type="button" style={shared}>
          {props.text}
        </button>
      );
    },
    Table: ({ props }) => (
      <div style={{ width: "100%", overflowX: "auto", border: `1px solid ${palette.border}`, borderRadius: "14px" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: "320px" }}>
          <thead>
            <tr style={{ background: "rgba(255,255,255,0.03)" }}>
              {props.columns.map((column, index) => (
                <th
                  key={`${column}-${index}`}
                  style={{
                    textAlign: "left",
                    padding: "12px 14px",
                    fontSize: "12px",
                    color: palette.textMuted,
                    borderBottom: `1px solid ${palette.border}`,
                  }}
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {props.rows.map((row, rowIndex) => (
              <tr key={`row-${rowIndex}`}>
                {row.map((value, cellIndex) => (
                  <td
                    key={`cell-${rowIndex}-${cellIndex}`}
                    style={{
                      padding: "12px 14px",
                      fontSize: "13px",
                      color: palette.text,
                      borderBottom: rowIndex === props.rows.length - 1 ? "none" : `1px solid ${palette.border}`,
                    }}
                  >
                    {value == null ? "—" : String(value)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    ),
  },
});

function Placeholder() {
  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", background: palette.bg, padding: "20px" }}>
      <div
        style={{
          width: "min(680px, 100%)",
          borderRadius: "20px",
          border: `1px solid ${palette.border}`,
          background: palette.surface,
          padding: "22px",
          boxShadow: "0 20px 48px rgba(0,0,0,0.24)",
        }}
      >
        <div style={{ display: "flex", gap: "10px", marginBottom: "16px", alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ width: 10, height: 10, borderRadius: "999px", background: palette.accent }} />
          <span style={{ fontSize: "12px", textTransform: "uppercase", letterSpacing: "0.08em", color: palette.textMuted }}>json-render MCP</span>
        </div>
        <h1 style={{ margin: 0, color: palette.text, fontSize: "22px", lineHeight: 1.2 }}>Waiting for a rendered spec</h1>
        <p style={{ margin: "10px 0 0", color: palette.textMuted, fontSize: "14px", lineHeight: 1.6 }}>
          Use the MCP tool from Claude, VS Code, or Codex to send a json-render spec. This iframe will render the result inline.
        </p>
      </div>
    </div>
  );
}

function App() {
  const { spec, loading, error } = useJsonRenderApp({ name: "json-render-mcp", version: "1.0.0" });

  if (error) {
    return (
      <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", background: palette.bg, color: palette.text, padding: "20px" }}>
        <div style={{ width: "min(680px, 100%)", borderRadius: "20px", border: `1px solid ${palette.border}`, background: palette.surface, padding: "22px" }}>
          <h1 style={{ margin: 0, fontSize: "20px" }}>json-render failed to connect</h1>
          <p style={{ margin: "10px 0 0", color: palette.textMuted, fontSize: "14px" }}>{error.message}</p>
        </div>
      </div>
    );
  }

  if (!spec) {
    return <Placeholder />;
  }

  return (
    <div style={{ minHeight: "100vh", background: palette.bg, padding: "20px", color: palette.text }}>
      <div style={{ width: "min(960px, 100%)", margin: "0 auto" }}>
        <JSONUIProvider registry={registry} initialState={spec.state ?? {}}>
          <Renderer spec={spec} registry={registry} loading={loading} />
        </JSONUIProvider>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
