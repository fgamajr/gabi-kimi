import { defineCatalog } from "@json-render/core";
import { schema } from "@json-render/react/schema";
import { z } from "zod";

const spacing = z.number().int().min(0).max(40).optional();
const tone = z.enum(["default", "muted", "accent", "success", "warning", "danger"]).optional();

export const catalog = defineCatalog(schema, {
  components: {
    Stack: {
      description:
        "Layout container that arranges child elements vertically or horizontally with configurable spacing.",
      props: z.object({
        direction: z.enum(["vertical", "horizontal"]).optional(),
        gap: spacing,
        padding: spacing,
        align: z.enum(["start", "center", "end", "stretch"]).optional(),
        justify: z.enum(["start", "center", "end", "between"]).optional(),
      }),
    },
    Grid: {
      description: "Responsive grid container for cards, metrics, or compact panels.",
      props: z.object({
        columns: z.number().int().min(1).max(4),
        gap: spacing,
      }),
    },
    Card: {
      description: "Surface card for grouped content, metrics, or summaries.",
      props: z.object({
        title: z.string().optional(),
        subtitle: z.string().optional(),
        tone,
      }),
    },
    Heading: {
      description: "Heading text for titles and section headers.",
      props: z.object({
        text: z.string(),
        level: z.number().int().min(1).max(4).optional(),
      }),
    },
    Text: {
      description: "Body text, caption, or supporting copy.",
      props: z.object({
        text: z.string(),
        variant: z.enum(["body", "muted", "small", "lead", "code"]).optional(),
      }),
    },
    Badge: {
      description: "Compact status or category label.",
      props: z.object({
        text: z.string(),
        tone,
      }),
    },
    Divider: {
      description: "Visual separator, optionally with a label.",
      props: z.object({
        label: z.string().optional(),
      }),
    },
    Button: {
      description: "Call-to-action button. Use href when linking to an external resource.",
      props: z.object({
        text: z.string(),
        href: z.string().optional(),
        tone,
      }),
    },
    Table: {
      description: "Compact tabular data with string headers and rows.",
      props: z.object({
        columns: z.array(z.string()).min(1),
        rows: z.array(z.array(z.union([z.string(), z.number(), z.boolean(), z.null()]))),
      }),
    },
  },
  actions: {},
});
