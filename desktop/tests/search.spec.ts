import { expect, test } from "@playwright/test";

// End-to-end smoke test for the desktop workflow. This runs against the
// bundled Tauri shell and its local sidecar (see playwright.config.ts and the
// desktop entrypoint). It assumes the sidecar is reachable through the
// runtime-config bridge injected by the Rust shell.

test("imports a resume and finds it", async ({ page }) => {
  await page.goto("/");

  const fileInput = page.locator('input[aria-label="选择简历文件"]');
  await fileInput.setInputFiles("testData/resume.pdf");

  await expect(page.getByText("解析完成")).toBeVisible();

  await page.getByLabel("人才搜索").fill("Python");
  await page.getByRole("button", { name: "搜索" }).click();

  await expect(page.getByRole("row", { name: /Python/ })).toBeVisible();
});