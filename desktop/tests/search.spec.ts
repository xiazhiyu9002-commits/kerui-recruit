import { expect, test } from "@playwright/test";

// End-to-end smoke tests for resume import, indexing and human review. The
// Playwright config starts an isolated local sidecar and Vite server.
const RESUME_FIXTURE = "tests/fixtures/resume.pdf";

test("imports a resume and finds it", async ({ page }) => {
  await page.goto("/");

  const fileInput = page.locator('input[aria-label="选择简历文件"]');
  await fileInput.setInputFiles(RESUME_FIXTURE);

  await expect(page.getByRole("heading", { name: /候选人（共 [1-9]/ })).toBeVisible({ timeout: 30_000 });

  await page.getByLabel("人才搜索").fill("Python");
  await expect(async () => {
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await expect(page.getByRole("row", { name: /Python/ })).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 30_000, intervals: [500, 1_000, 2_000] });
});

test("opens a resume revision and confirms its human review", async ({ page }) => {
  await page.goto("/");

  await page.locator('input[aria-label="选择简历文件"]').setInputFiles(RESUME_FIXTURE);
  await expect(page.getByRole("heading", { name: /候选人（共 [1-9]/ })).toBeVisible({ timeout: 30_000 });

  await page.getByLabel("人才搜索").fill("Python");
  await expect(async () => {
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await expect(page.getByRole("row", { name: /Python/ })).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 30_000, intervals: [500, 1_000, 2_000] });
  await page.getByRole("row", { name: /Python/ }).getByRole("button", { name: "解析与方向" }).first().click();

  const drawer = page.getByRole("dialog", { name: "简历复核" });
  await expect(drawer.getByText("原始简历正文")).toBeVisible();
  await expect(drawer.getByRole("button", { name: "确认复核并入库" })).toBeVisible();

  await drawer.getByLabel("复核姓名").fill("端到端候选人");
  await drawer.getByRole("button", { name: "确认复核并入库" }).click();
  await expect(drawer.getByText("复核已通过")).toBeVisible();
});
