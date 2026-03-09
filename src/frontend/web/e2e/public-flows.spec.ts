import { test, expect } from "./fixtures/test";

const STABLE_SCREENSHOT_OPTIONS = {
  animations: "disabled" as const,
  caret: "hide" as const,
  scale: "css" as const,
};

test("home and search remain deterministic with mocked public data", async ({ page, mockApi }) => {
  await mockApi(page, { session: "visitor" });

  await page.goto("/");

  await expect(page.getByRole("heading", { name: /GABI/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /licitação/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /Portaria de Licitação Integrada/i })).toBeVisible();
  await expect(page.locator("main")).toHaveScreenshot("home-public.png", STABLE_SCREENSHOT_OPTIONS);

  await page.getByRole("button", { name: /licitação/i }).click();

  await expect(page).toHaveURL(/\/busca\?q=licita%C3%A7%C3%A3o/);
  await expect(page.getByText("2 resultado(s)")).toBeVisible();
  await expect(page.getByRole("link", { name: /Aviso de Licitação para Infraestrutura Regional/i })).toBeVisible();

  await page.getByRole("button", { name: "DO2" }).click();

  await expect(page).toHaveURL(/section=DO2/);
  await expect(page.getByText("1 resultado(s)")).toBeVisible();
  await expect(page.locator("main")).toHaveScreenshot("search-results-do2.png", STABLE_SCREENSHOT_OPTIONS);
});

test("guests are redirected to login when opening an admin route", async ({ page, mockApi }) => {
  await mockApi(page, { session: "visitor" });

  await page.goto("/admin/upload");

  await expect(page.getByLabel(/Chave de acesso|Access key/i)).toBeVisible();
  await expect(page).toHaveURL(/\/login(?:\?redirect=%2Fadmin%2Fupload)?/);
  await expect(page.getByRole("heading", { name: /GABI/i })).toBeVisible();
});
