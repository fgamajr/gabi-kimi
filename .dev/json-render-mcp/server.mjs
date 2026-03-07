import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { createMcpApp } from "@json-render/mcp";
import { catalog } from "./catalog.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distHtml = path.join(__dirname, "dist", "index.html");
const buildScript = path.join(__dirname, "build-ui.mjs");

function ensureBuilt() {
  if (fs.existsSync(distHtml)) {
    return;
  }

  const result = spawnSync(process.execPath, [buildScript], {
    cwd: __dirname,
    stdio: ["ignore", "pipe", "pipe"],
    encoding: "utf8",
  });

  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || "failed to build json-render iframe");
  }
}

ensureBuilt();

const html = fs.readFileSync(distHtml, "utf8");
const server = await createMcpApp({
  name: "json-render",
  version: "1.0.0",
  catalog,
  html,
  tool: {
    name: "render_json_ui",
    title: "Render JSON UI",
    description:
      "Render an interactive UI from a json-render spec using the available components: Stack, Grid, Card, Heading, Text, Badge, Divider, Button, and Table.",
  },
});

await server.connect(new StdioServerTransport());
