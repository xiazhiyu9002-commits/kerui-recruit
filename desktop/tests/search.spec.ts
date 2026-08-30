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

test("opens a resume revision and audits a candidate correction", async ({ page }) => {
  await page.goto("/");

  await page.locator('input[aria-label="选择简历文件"]').setInputFiles("testData/resume.pdf");
  await expect(page.getByText("解析完成")).toBeVisible();

  await page.getByLabel("人才搜索").fill("Python");
  await page.getByRole("button", { name: "搜索" }).click();
  await page.getByRole("row", { name: /Python/ }).getByRole("button", { name: "查看详情" }).first().click();

  const drawer = page.getByLabel("候选人详情");
  await expect(drawer.getByText("简历版本")).toBeVisible();
  await expect(drawer.getByText("当前版本")).toBeVisible();

  await drawer.getByLabel("候选人显示名称").fill("端到端候选人");
  await drawer.getByRole("button", { name: "保存名称更正" }).click();
  await expect(drawer.getByText("更正已保存")).toBeVisible();
  await drawer.getByRole("button", { name: "撤销本次更正" }).click();
  await expect(drawer.getByText("更正已撤销")).toBeVisible();
});
