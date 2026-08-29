import { expect, test } from "@playwright/test";

// End-to-end smoke tests for the main recruitment workflows. Like
// search.spec.ts, these run against the bundled Tauri shell and its local
// sidecar, which inject the runtime-config bridge consumed by the React app.

test("imports a JD and runs a match", async ({ page }) => {
  await page.goto("/");

  await page.getByText("JD 管理").click();
  await page.getByLabel("JD 岗位").fill("Java 后端工程师");
  await page.getByLabel("JD 原文").fill("负责支付系统，3 年 Java，本科，金融");
  await page.getByRole("button", { name: "导入并解析" }).click();
  await expect(page.getByText("导入成功")).toBeVisible();

  const revisionId = await page.locator("code").first().textContent();
  await page.getByText("人岗匹配").click();
  await page.getByLabel("匹配 JD 版本").fill(revisionId ?? "");
  await page.getByRole("button", { name: "开始匹配" }).click();
  await expect(page.getByText("匹配结果")).toBeVisible();
});

test("loads the recruitment dashboard", async ({ page }) => {
  await page.goto("/");
  await page.getByText("数据看板").click();
  await page.getByRole("button", { name: "刷新看板" }).click();
  await expect(page.getByText("推荐总数")).toBeVisible();
});

test("creates a mapping project and builds a tree", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Mapping").click();
  await page.getByLabel("项目名称").fill("互联网公司图谱");
  await page.getByRole("button", { name: "新建项目" }).click();
  await expect(page.getByText("互联网公司图谱")).toBeVisible();
});

test("searches BD leads", async ({ page }) => {
  await page.goto("/");
  await page.getByText("BD 助手").click();
  await page.getByLabel("BD 搜索").fill("Java 工程师 招聘 上海");
  await page.getByRole("button", { name: "搜索线索" }).click();
  await expect(page.getByText("暂无线索")).toBeVisible();
});

test("runs the health check and lists backups", async ({ page }) => {
  await page.goto("/");
  await page.getByText("设置").click();
  await page.getByRole("button", { name: "运行检测" }).click();
  await expect(page.getByText("数据库")).toBeVisible();
  await page.getByRole("button", { name: "加载备份" }).click();
  await expect(page.getByText("暂无备份快照")).toBeVisible();
});
