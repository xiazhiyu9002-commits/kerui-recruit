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
    })
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
});
