import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { buildAppHtml } from "@json-render/mcp/app";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(__dirname, "dist");
const entryPoint = path.join(__dirname, "app.jsx");

await fs.promises.mkdir(outDir, { recursive: true });

const result = await build({
  entryPoints: [entryPoint],
  bundle: true,
  format: "esm",
  platform: "browser",
  target: ["es2020"],
  jsx: "automatic",
  write: false,
  minify: true,
});

const js = result.outputFiles[0].text;
const css = `
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body, #root { margin: 0; min-height: 100%; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
  body { background: #0f1220; }
  button, input, select, textarea { font: inherit; }
  a { color: inherit; }
`;

const html = buildAppHtml({
  title: "json-render MCP",
  css,
  js,
});

await fs.promises.writeFile(path.join(outDir, "index.html"), html, "utf8");
console.log(`built ${path.join(outDir, "index.html")}`);
