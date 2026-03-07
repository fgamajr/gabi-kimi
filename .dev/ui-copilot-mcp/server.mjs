import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const server = new McpServer({
  name: "ui-copilot",
  version: "1.0.0",
});

const stackSchema = z.enum(["react", "nextjs", "vite-react", "vite-monorepo", "unknown"]).default("vite-react");
const platformSchema = z.enum(["web", "mobile-web", "desktop-web", "hybrid"]).default("web");

function chooseSources({ goal, needsAuth, needsAnimation, needsMarketing, stack }) {
  const picks = [];
  const normalizedGoal = goal.toLowerCase();

  if (stack === "nextjs" || stack === "react" || stack === "vite-react" || stack === "vite-monorepo") {
    picks.push({
      source: "shadcn/ui",
      fit: "high",
      why: "Best default for composable React app surfaces, forms, dialogs, tables, and command menus.",
      when: "Use for app shell, auth screens, search panels, settings, data tables, and command palette foundations.",
    });
  }

  if (needsMarketing || /hero|landing|homepage|marketing/.test(normalizedGoal)) {
    picks.push({
      source: "Tailark",
      fit: "high",
      why: "Good for polished marketing/hero sections and landing-page composition.",
      when: "Use for homepage hero, editorial landing blocks, CTA bands, or showcase sections.",
    });
  }

  if (needsAnimation || /motion|animate|micro-motion|headline|text effect/.test(normalizedGoal)) {
    picks.push({
      source: "React Bits",
      fit: "high",
      why: "Good source for expressive animation patterns without inventing motion from scratch.",
      when: "Use for headline animation, text reveals, card entrances, decorative motion, or attention cues.",
    });
  }

  if (needsAuth || /sign in|login|clerk|authentication|auth/.test(normalizedGoal)) {
    picks.push({
      source: "Clerk",
      fit: "high",
      why: "Fastest route for production-ready auth flows in React/Next stacks.",
      when: "Use for sign-in, sign-up, session handling, protected routes, user profile, and auth middleware.",
    });
  }

  if (!picks.length) {
    picks.push({
      source: "shadcn/ui",
      fit: "default",
      why: "Safest default for React UI work when the task is not obviously marketing or motion heavy.",
      when: "Start here, then layer Tailark or React Bits only where needed.",
    });
  }

  return picks;
}

function buildAgentPrompt({ task, stack, platform, picks, constraints }) {
  const pickSummary = picks
    .map((pick) => `- ${pick.source}: ${pick.why} (${pick.when})`)
    .join("\n");

  const constraintLines = constraints.length
    ? constraints.map((constraint) => `- ${constraint}`).join("\n")
    : "- Preserve existing project structure unless the task explicitly asks for a refactor.";

  return `You are a senior frontend/product engineer working inside an existing repository.

Task:
${task}

Project assumptions:
- Stack: ${stack}
- Platform: ${platform}
- Available source libraries/patterns to consider:
${pickSummary}

Execution requirements:
- Prefer adapting the existing codebase over rewriting from scratch.
- Preserve runtime behavior unless the task explicitly changes it.
- Favor production-grade code over demos.
- If multiple sources fit, combine them intentionally instead of mixing styles randomly.
- Explain tradeoffs in implementation choices.

Constraints:
${constraintLines}

Deliver:
1. Brief diagnosis
2. Concrete implementation plan
3. Code changes
4. Validation steps
5. Residual risks or follow-ups`;
}

server.registerTool(
  "recommend_ui_sources",
  {
    description:
      "Recommend which UI source patterns to use for a task: shadcn/ui, Tailark, React Bits, Clerk, or a combination.",
    inputSchema: {
      goal: z.string().min(1).describe("What you want to build or improve."),
      stack: stackSchema.describe("Current app stack."),
      needsAuth: z.boolean().optional().describe("Whether the task includes authentication UX."),
      needsAnimation: z.boolean().optional().describe("Whether the task includes motion-heavy UX."),
      needsMarketing: z.boolean().optional().describe("Whether the task includes hero/landing marketing sections."),
    },
  },
  async ({ goal, stack, needsAuth = false, needsAnimation = false, needsMarketing = false }) => {
    const recommendations = chooseSources({ goal, stack, needsAuth, needsAnimation, needsMarketing });
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({ goal, stack, recommendations }, null, 2),
        },
      ],
      structuredContent: { goal, stack, recommendations },
    };
  }
);

server.registerTool(
  "generate_ui_agent_prompt",
  {
    description:
      "Generate a strong implementation prompt for another coding/design agent, using the most appropriate UI sources and execution constraints.",
    inputSchema: {
      task: z.string().min(1).describe("The exact frontend/product task you want another agent to perform."),
      stack: stackSchema.describe("Current app stack."),
      platform: platformSchema.describe("Delivery platform."),
      needsAuth: z.boolean().optional(),
      needsAnimation: z.boolean().optional(),
      needsMarketing: z.boolean().optional(),
      constraints: z.array(z.string()).optional().describe("Extra constraints the agent must obey."),
    },
  },
  async ({
    task,
    stack,
    platform,
    needsAuth = false,
    needsAnimation = false,
    needsMarketing = false,
    constraints = [],
  }) => {
    const picks = chooseSources({ goal: task, stack, needsAuth, needsAnimation, needsMarketing });
    const prompt = buildAgentPrompt({ task, stack, platform, picks, constraints });
    return {
      content: [{ type: "text", text: prompt }],
      structuredContent: { prompt, picks },
    };
  }
);

server.registerTool(
  "plan_ui_execution",
  {
    description:
      "Produce a concrete UI implementation plan with source selection, sequencing, and integration notes for React/Vite/Next projects.",
    inputSchema: {
      task: z.string().min(1).describe("What you want to build."),
      stack: stackSchema.describe("Current app stack."),
      platform: platformSchema.describe("Target platform."),
      repoContext: z.string().optional().describe("Short description of the current app, routes, or relevant architecture."),
    },
  },
  async ({ task, stack, platform, repoContext = "" }) => {
    const picks = chooseSources({
      goal: task,
      stack,
      needsAuth: /auth|login|sign in|clerk/i.test(task),
      needsAnimation: /animate|motion|hero|headline/i.test(task),
      needsMarketing: /hero|landing|marketing|homepage/i.test(task),
    });

    const plan = {
      task,
      stack,
      platform,
      repoContext,
      sourceSelection: picks,
      executionOrder: [
        "Audit the existing page or flow and identify the minimal surface area to change.",
        "Choose the base component source that best fits the task.",
        "Add only the components/patterns that match the current visual language or the explicit redesign goal.",
        "Integrate motion/auth/marketing layers only where they add user value.",
        "Validate build, runtime behavior, and accessibility-critical interactions.",
      ],
      integrationNotes: [
        "Use shadcn/ui as the default app-surface foundation.",
        "Use Tailark only for marketing/hero sections, not for dense application shells.",
        "Use React Bits selectively for motion accents, not as the entire design system.",
        "Use Clerk only when the task explicitly includes auth/product identity flows.",
      ],
    };

    return {
      content: [{ type: "text", text: JSON.stringify(plan, null, 2) }],
      structuredContent: plan,
    };
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);
