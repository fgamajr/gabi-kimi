import { test as base, expect } from "@playwright/test";
import { installApiMocks } from "./mockApi";

export const test = base.extend<{
  mockApi: typeof installApiMocks;
}>({
  page: async ({ page }, use) => {
    await page.addInitScript(() => {
      window.localStorage.clear();
      window.sessionStorage.clear();
    });
    await use(page);
  },
  mockApi: async ({}, use) => {
    await use(installApiMocks);
  },
});

export { expect };
