import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import { App, type RecruitmentApi } from "../src/App";


function fakeApi(): RecruitmentApi {
  return {
    importResume: async () => ({
      candidate_id: "candidate-1",
      document_id: "document-1",
      revision_id: "revision-1",
      blob_id: "blob-1",
      task_id: "task-1"
    }),
    getTask: async () => ({
      id: "task-1",
      task_type: "PARSE_RESUME",
      status: "SUCCESS",
      progress: 100,
      error_message: null
    }),
    searchCandidates: async () => ({
      items: [
        {
          candidate_id: "candidate-1",
          revision_id: "revision-1",
          content: "张三 Python 金融风控",
          score: 0.98,
          matched_channels: ["bm25", "vector"],
          total_years: 6,
          highest_degree: "MASTER",
          location: "上海"
        }
      ],
      degraded_reasons: []
    }),
    importJd: async () => ({ jd_id: "jd-1", revision_id: "rev-1" }),
    matchJd: async () => ({
      run_id: "run-1",
      items: [
        {
          candidate_id: "candidate-1",
          revision_id: "revision-1",
          content: "张三 Python 金融风控",
          score: 0.95,
          matched_channels: ["bm25", "vector"],
          total_years: 6,
          highest_degree: "MASTER",
          location: "上海"
        }
      ]
    }),
    health: async () => ({
      database: { status: "healthy" },
      search: { status: "healthy" }
    }),
    diagnostics: async () => ({
      sqlite_version: "3.45.3",
      database_path: "/tmp/recruit.sqlite3",
      database_size_bytes: 2048,
      counts: { candidate: 3, jd: 1 },
      pragmas: { journal_mode: "wal" }
    }),
    listMappingProjects: async () => [],
    createMappingProject: async (name: string) => ({ id: "proj-1", name, description: null }),
    buildMappingTree: async () => ({ id: "snap-1", label: "v1", is_current: true }),
    listMappingSnapshots: async () => [],
    getMappingTree: async () => [],
    searchBdLeads: async () => [],
    searchLeadsForCandidate: async () => [],
    updateLeadStatus: async () => ({ id: "lead-1", source: "web", company_name: "某公司", job_title: null, raw_snippet: null, url: null, status: "已联系" }),
    createCase: async () => ({ id: "case-1", candidate_id: "candidate-1", jd_id: "jd-1", stage: "待评估", note: null }),
    listCases: async () => [],
    advanceCase: async () => ({ id: "case-1", candidate_id: "candidate-1", jd_id: "jd-1", stage: "已推荐", note: null }),
    undoCase: async () => ({ id: "case-1", candidate_id: "candidate-1", jd_id: "jd-1", stage: "待评估", note: null }),
    getCaseEvents: async () => [],
    dashboardOverview: async () => ({
      recommendation_total: 1,
      funnel: [{ stage: "待评估", count: 1 }, { stage: "已推荐", count: 1 }],
      health: { candidate_total: 2, ready_total: 1, parse_failed: 0, recent_30d: 1, open_jd_total: 1 }
    }),
    dashboardByJd: async () => [],
    reverseMatch: async () => [],
    listDeleted: async () => [],
    restoreDeleted: async () => ({ entity_type: "candidate", entity_id: "candidate-1", deleted: false }),
    exportMappingTree: async () => undefined,
    getSettings: async () => ({}),
    updateSettings: async () => ({})
  };
}


describe("desktop recruitment workflow", () => {
  test("searches candidates and opens the evidence drawer", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.type(screen.getByPlaceholderText("搜索人才、技能、公司或自然语言"), "Python 金融");
    await user.click(screen.getByRole("button", { name: "搜索" }));

    expect(await screen.findByText("张三 Python 金融风控")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "查看详情" }));
    expect(screen.getByRole("complementary", { name: "候选人详情" })).toHaveTextContent("6 年经验");
  });

  test("uploads a resume and shows its durable task", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);
    const file = new File(["resume"], "张三.pdf", { type: "application/pdf" });

    await user.upload(screen.getByLabelText("选择简历文件"), file);

    expect(await screen.findByText("解析完成")).toBeVisible();
    expect(screen.getByText("task-1")).toBeVisible();
  });

  test("imports a JD and shows its revision id", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(screen.getByText("JD 管理"));
    await user.type(screen.getByLabelText("JD 岗位"), "Java 后端工程师");
    await user.type(screen.getByLabelText("JD 原文"), "负责支付系统，3年 Java");
    await user.click(screen.getByRole("button", { name: "导入并解析" }));

    expect(await screen.findByText("rev-1")).toBeVisible();
  });

  test("runs JD match and shows candidates", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(screen.getByText("人岗匹配"));
    await user.type(screen.getByLabelText("匹配 JD 版本"), "rev-1");
    await user.click(screen.getByRole("button", { name: "开始匹配" }));

    expect(await screen.findByText("匹配结果")).toBeVisible();
    expect(screen.getByText("张三 Python 金融风控")).toBeVisible();
  });

  test("loads the recruitment dashboard", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(screen.getByText("数据看板"));
    await user.click(screen.getByRole("button", { name: "刷新看板" }));

    expect(await screen.findByText("推荐总数")).toBeVisible();
    expect(screen.getByText("面试漏斗")).toBeVisible();
  });

  test("creates a mapping project", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(screen.getByText("Mapping"));
    await user.type(screen.getByLabelText("项目名称"), "互联网公司图谱");
    await user.click(screen.getByRole("button", { name: "新建项目" }));

    expect(await screen.findByText("互联网公司图谱")).toBeVisible();
  });

  test("searches BD leads and shows empty state", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(screen.getByText("BD 助手"));
    await user.type(screen.getByLabelText("BD 搜索"), "Java 工程师");
    await user.click(screen.getByRole("button", { name: "搜索线索" }));

    expect(await screen.findByText("暂无线索")).toBeVisible();
  });

  test("shows recruitment pipeline section in candidate detail", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.type(screen.getByPlaceholderText("搜索人才、技能、公司或自然语言"), "Python");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    await user.click(await screen.findByRole("button", { name: "查看详情" }));

    expect(await screen.findByText("招聘流程")).toBeVisible();
    expect(screen.getByText("暂无进行中的流程")).toBeVisible();
  });
});
