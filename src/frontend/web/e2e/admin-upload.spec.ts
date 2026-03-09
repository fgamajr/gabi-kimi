import { test, expect } from "./fixtures/test";

const STABLE_SCREENSHOT_OPTIONS = {
  animations: "disabled" as const,
  caret: "hide" as const,
  scale: "css" as const,
};

test("admin upload flow works against mocked network responses", async ({ page, mockApi }) => {
  await mockApi(page, { session: "admin" });

  await page.goto("/admin/upload");

  await expect(page.getByRole("heading", { name: "Upload DOU" })).toBeVisible();

  await page.locator("#admin-upload-file").setInputFiles({
    name: "dou-sample.xml",
    mimeType: "application/xml",
    buffer: Buffer.from(
      "<root><materia><section>DO2</section><pubName>DO2</pubName><data>2026-03-08</data></materia></root>",
      "utf-8",
    ),
  });

  await expect(page.getByText("dou-sample.xml")).toBeVisible();
  await expect(page.getByText("Artigos detectados: 1")).toBeVisible();
  await expect(page.getByText("Período: 2026-03-08 a 2026-03-08")).toBeVisible();
  await expect(page.locator("main")).toHaveScreenshot("admin-upload-selected-file.png", STABLE_SCREENSHOT_OPTIONS);

  await page.getByRole("button", { name: "Enviar" }).click();

  await expect(page.getByText("Job criado: job-123")).toBeVisible();
  await expect(page.getByText("dou-sample.xml")).not.toBeVisible();
});
