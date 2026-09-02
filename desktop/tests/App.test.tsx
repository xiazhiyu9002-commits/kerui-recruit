import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import { App, type CaseDetail, type CaseEventItem, type RecruitmentApi } from "../src/App";

function recruitmentFixture() {
  const api = fakeApi();
  const event = (id: string, event_type: string, result: string | null = null, time = "2026-08-30T00:00:00Z"): CaseEventItem => ({
    id, event_type, result, case_round_id: event_type.startsWith("INTERVIEW") ? "round-1" : null,
    round_name: event_type.startsWith("INTERVIEW") ? "终面" : null,
    occurred_at: time, recorded_at: time, note: null, status: "active",
  });
  const detail: CaseDetail = {
    id: "case-1", candidate_id: "candidate-1", jd_id: "jd-1", stage: "初试", note: null,
    rounds: [{ id: "round-1", round_no: 1, round_name: "终面", round_type: null, skipped: false }],
    events: [event("recommend", "RECOMMENDED"), event("entered", "INTERVIEW_ENTERED"), event("pending", "INTERVIEW_RESULT", "待反馈")],
  };
  api.getCase = async () => structuredClone(detail);
  api.listCases = async () => [structuredClone(detail)];
  api.recordResult = async (_caseId, roundId, result) => {
    const next = { ...event("result-final", "INTERVIEW_RESULT", result, "2026-08-31T02:00:00Z"), case_round_id: roundId };
    detail.events.push(next);
    return next;
  };
  api.voidEvent = async (id) => {
    detail.events = detail.events.filter((item) => item.id !== id);
    return { deleted: id };
  };
  return { api, event, detail };
}

async function openRecruitment(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /招聘流程/ }));
  await user.click(await screen.findByRole("button", { name: "查看流程" }));
  return screen.getByRole("dialog", { name: "招聘流程" });
}

function selectTime(dialog: HTMLElement) {
  fireEvent.change(within(dialog).getByLabelText("发生时间（上海）"), { target: { value: "2026-08-30T15:30" } });
}

describe("recruitment consistency through the App", () => {

  test("creates a linked case reminder using Shanghai time and shows its paused state", async () => {
    const fixture = recruitmentFixture();
    fixture.detail.candidate_name = "张三";
    fixture.detail.jd_title = "后端";
    const submitted: unknown[] = [];
    fixture.api.createReminder = async (input) => {
      submitted.push(input);
      return { id: "linked-1", title: input.title, note: null, remind_at: "2026-09-02T01:30:00Z", dismissed: false, dismissed_at: null, case_id: input.case_id, paused_by_workflow: true };
    };
    const user = userEvent.setup();
    render(<App api={fixture.api} />);
    const dialog = await openRecruitment(user);
    const reminderSection = within(dialog).getByRole("region", { name: "本流程跟进提醒" });
    expect(within(reminderSection).getByLabelText("提醒内容")).toHaveValue("跟进 张三 · 后端");
    expect(within(reminderSection).getByRole("button", { name: "添加提醒" })).toBeDisabled();
    fireEvent.change(within(reminderSection).getByLabelText("提醒时间（上海）"), { target: { value: "2026-09-02T09:30" } });
    await user.dblClick(within(reminderSection).getByRole("button", { name: "添加提醒" }));
    expect(await within(reminderSection).findByText("跟进 张三 · 后端", { selector: "strong" })).toBeVisible();
    expect(within(reminderSection).getByText("2026/9/2 09:30:00（上海）")).toBeVisible();
    expect(within(reminderSection).getByText("已暂停：候选人、岗位或流程状态暂不允许跟进；状态恢复后自动继续。")).toBeVisible();
    expect(submitted).toEqual([{ title: "跟进 张三 · 后端", remind_at: "2026-09-02T09:30:00+08:00", case_id: "case-1" }]);
  });

  test("keeps generic reminders available and opens a linked case from reminder management", async () => {
    const fixture = recruitmentFixture();
    fixture.api.listReminders = async () => [{ id: "linked-1", title: "客户反馈", note: null, remind_at: "2026-09-02T01:30:00Z", dismissed: false, dismissed_at: null, case_id: "case-1", paused_by_workflow: true }];
    let submitted: unknown;
    fixture.api.createReminder = async (input) => {
      submitted = input;
      return { id: "generic-1", title: input.title, note: null, remind_at: "2026-09-03T01:30:00Z", dismissed: false, dismissed_at: null, case_id: null, paused_by_workflow: false };
    };
    const user = userEvent.setup();
    render(<App api={fixture.api} />);
    await user.click(screen.getByText("设置"));
    const section = await screen.findByRole("region", { name: "提醒管理" });
    expect(await within(section).findByText("客户反馈")).toBeVisible();
    await user.type(within(section).getByLabelText("提醒内容"), "整理周报");
    fireEvent.change(within(section).getByLabelText("提醒时间（上海）"), { target: { value: "2026-09-03T09:30" } });
    await user.click(within(section).getByRole("button", { name: "添加提醒" }));
    expect(await within(section).findByText("整理周报", { selector: "strong" })).toBeVisible();
    expect(submitted).toEqual({ title: "整理周报", remind_at: "2026-09-03T09:30:00+08:00", case_id: undefined });
    await user.click(within(section).getByRole("button", { name: "查看关联流程" }));
    expect(await screen.findByRole("dialog", { name: "招聘流程" })).toBeVisible();
  });



  test.each(["passed", "pending"] as const)("requires an explicit name to add a round after a final %s round", async (state) => {
    const fixture = recruitmentFixture();
    fixture.detail.process_rounds = [{ round_no: 1, round_name: "终面" }];
    if (state === "passed") fixture.detail.events.push(fixture.event("final-pass", "INTERVIEW_RESULT", "通过", "2026-08-31T00:00:00Z"));
    let enteredName: string | undefined;
    function addRound(name?: string) {
      enteredName = name;
      const entered = { ...fixture.event("entered-2", "INTERVIEW_ENTERED", null, "2026-08-31T02:00:00Z"), case_round_id: "round-2", round_name: name || null };
      fixture.detail.rounds.push({ id: "round-2", round_no: 2, round_name: name || "", round_type: null, skipped: false });
      fixture.detail.events.push(entered);
      return entered;
    }
    fixture.api.enterInterview = async (_caseId, payload) => addRound(payload?.round_name);
    fixture.api.passAndAdvance = async (_caseId, _roundId, payload) => {
      const passed = fixture.event("final-pass", "INTERVIEW_RESULT", "通过", "2026-08-31T01:00:00Z");
      fixture.detail.events.push(passed);
      return [passed, addRound(payload?.next_round_name)];
    };
    const user = userEvent.setup();
    render(<App api={fixture.api} />);
    const dialog = await openRecruitment(user);
    expect(within(dialog).getByRole("button", { name: "进入面试" })).toBeDisabled();
    expect(within(dialog).queryByRole("button", { name: "通过进下一轮" })).not.toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("临时轮次名称"), "   ");
    expect(within(dialog).getByRole("button", { name: "进入面试" })).toBeDisabled();
    expect(within(dialog).queryByRole("button", { name: "通过进下一轮" })).not.toBeInTheDocument();
    await user.clear(within(dialog).getByLabelText("临时轮次名称"));
    await user.type(within(dialog).getByLabelText("临时轮次名称"), "  补充沟通  ");
    selectTime(dialog);
    await user.click(within(dialog).getByRole("button", { name: state === "passed" ? "进入面试" : "通过进下一轮" }));
    expect(await within(dialog).findByText("第2轮 · 补充沟通")).toBeVisible();
    expect(enteredName).toBe("补充沟通");
    expect(fixture.detail.process_rounds).toEqual([{ round_no: 1, round_name: "终面" }]);
    expect(within(dialog).getByLabelText("临时轮次名称")).toHaveValue("");
  });

  test("still blocks named add-on interviews after an offer was issued", async () => {
    const fixture = recruitmentFixture();
    fixture.detail.process_rounds = [{ round_no: 1, round_name: "终面" }];
    fixture.detail.events.push(fixture.event("offer-issued", "OFFER", "已发放", "2026-08-31T00:00:00Z"));
    const user = userEvent.setup();
    render(<App api={fixture.api} />);
    const dialog = await openRecruitment(user);
    await user.type(within(dialog).getByLabelText("临时轮次名称"), "补充沟通");
    expect(within(dialog).getByRole("button", { name: "进入面试" })).toBeDisabled();
    expect(within(dialog).queryByRole("button", { name: "通过进下一轮" })).not.toBeInTheDocument();
    expect(fixture.detail.rounds).toHaveLength(1);
  });



  test("separates incompatible index versions from retryable sync failures", async () => {
    const api = fakeApi();
    api.indexStatus = async () => ({
      pending: 0, failed: 0, items: [],
      indexes: [{ entity_type: "candidate", compatible: false, error: "INDEX_VERSION_MISMATCH" }, { entity_type: "jd", compatible: true, error: null }],
    });
    const user = userEvent.setup();
    render(<App api={api} />);
    await user.click(screen.getByText("设置"));
    const section = await screen.findByRole("region", { name: "索引同步" });
    expect(await within(section).findByText("候选人索引：版本不兼容")).toBeVisible();
    expect(within(section).getByText("INDEX_VERSION_MISMATCH")).toBeVisible();
    expect(within(section).getByText("需要受控重建或升级索引；重试同步不会修复版本不兼容。")).toBeVisible();
    expect(within(section).getByRole("button", { name: "重试失败同步" })).toBeDisabled();
    expect(within(section).getByText("岗位索引：版本兼容")).toBeVisible();
  });



  test("shows index sync failures and requests retry without claiming a rebuild or completion", async () => {
    const api = fakeApi();
    let retries = 0;
    api.indexStatus = async () => ({ pending: 2, failed: 1, items: [{ entity_type: "candidate", entity_id: "candidate-1", status: "RETRY_WAIT", attempts: 2, error: "TimeoutError" }] });
    let resolveRetry!: (value: Awaited<ReturnType<RecruitmentApi["retryIndexSync"]>>) => void;
    api.retryIndexSync = async () => { retries++; return new Promise((resolve) => { resolveRetry = resolve; }); };
    const user = userEvent.setup();
    render(<App api={api} />);
    await user.click(screen.getByText("设置"));
    const section = await screen.findByRole("region", { name: "索引同步" });
    expect(await within(section).findByText("TimeoutError")).toBeVisible();
    expect(within(section).getByText("等待同步 2 项，失败 1 项")).toBeVisible();
    await user.dblClick(within(section).getByRole("button", { name: "重试失败同步" }));
    expect(retries).toBe(1);
    expect(within(section).getByRole("button", { name: "重试失败同步" })).toBeDisabled();
    await act(async () => resolveRetry({ pending: 2, failed: 0, items: [{ entity_type: "candidate", entity_id: "candidate-1", status: "PENDING", attempts: 2, error: null }] }));
    expect(await within(section).findByText("已请求重试，等待后台同步完成。")).toBeVisible();
    expect(within(section).getByText("等待同步 2 项，失败 0 项")).toBeVisible();
    expect(within(section).queryByText("同步完成")).not.toBeInTheDocument();
  });

  test("makes a failed reparse visible even when the accepted resume remains READY", async () => {
    const api = fakeApi();
    api.listCandidates = async () => [{ candidate_id: "candidate-1", revision_id: "revision-1", display_name: "人工确认", total_years: 5, highest_degree: null, location: null, status: "AVAILABLE", revision_status: "READY", phone: null, original_filename: "resume.pdf", parsed_data: { name: "人工确认", skills: ["Python"] }, error_code: "E_OCR_FAILED", error_message: "重新解析失败，已保留人工资料" }];
    const user = userEvent.setup();
    render(<App api={api} />);
    expect(await screen.findByText("重新解析失败，已保留人工资料")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "解析异常 · 复核" }));
    expect(await screen.findByRole("dialog", { name: "简历复核" })).toBeVisible();
  });

  test("breaks equal event timestamps by event id like the backend projection", async () => {
    const fixture = recruitmentFixture();
    fixture.detail.events = [
      fixture.event("recommend", "RECOMMENDED"), fixture.event("entered", "INTERVIEW_ENTERED"),
      fixture.event("z-passed", "INTERVIEW_RESULT", "通过"),
      fixture.event("a-pending", "INTERVIEW_RESULT", "待反馈"),
    ];
    const user = userEvent.setup();
    render(<App api={fixture.api} />);
    const dialog = await openRecruitment(user);
    expect(within(dialog).getByLabelText("第1轮当前结果")).toHaveTextContent("通过");
    expect(within(dialog).queryByRole("button", { name: "通过（结束面试）" })).not.toBeInTheDocument();
  });


  test("reviews a failed resume without publishing drafts or losing corrections on validation failure", async () => {
    const api = fakeApi();
    let approved = false;
    api.listCandidates = async () => [{ candidate_id: "candidate-1", revision_id: "revision-1", display_name: "已确认姓名", total_years: 5, highest_degree: null, location: null, status: "ACTIVE", revision_status: approved ? "READY" : "FAILED", phone: null, original_filename: "resume.pdf", parsed_data: { name: "已确认姓名", skills: ["Python"] } }];
    const review = { revision_id: "revision-1", status: "FAILED", review_required: true, raw_text: "原始简历正文", parsed_data: { name: "已确认姓名", skills: ["Python"] }, review_data: { name: "机器姓名", skills: ["Java"], summary: "需要核实" }, manual_overrides: { name: "已确认姓名" }, extraction_diagnostics: { pages: [{ page_index: 0, reason: "low_text", route: "ocr", valid_char_count: 12 }], last_error: "OCR 不可用" }, error_code: "E_PENDING_REVIEW", error_message: "资料不足，请复核" };
    api.getResumeReview = async () => structuredClone(review);
    let attempts = 0;
    const submissions: Record<string, unknown>[] = [];
    api.approveResumeReview = async (_id, fields) => {
      submissions.push(fields);
      attempts++;
      if (attempts === 1) throw new Error("资料不足，请补充摘要");
      approved = true;
      return { ...review, status: "READY", review_required: false, parsed_data: { ...review.parsed_data, ...fields } };
    };
    const user = userEvent.setup();
    render(<App api={api} />);
    await user.click(await screen.findByRole("button", { name: "待复核" }));
    const dialog = await screen.findByRole("dialog", { name: "简历复核" });
    expect(within(dialog).getByLabelText("复核姓名")).toHaveValue("已确认姓名");
    expect(within(dialog).getByLabelText("复核技能")).toHaveValue("Python");
    expect(within(dialog).getByText("原始简历正文", { selector: "pre" })).toBeVisible();
    await user.clear(within(dialog).getByLabelText("复核技能"));
    await user.type(within(dialog).getByLabelText("复核技能"), "Python、Go");
    await user.clear(within(dialog).getByLabelText("复核摘要"));
    await user.type(within(dialog).getByLabelText("复核摘要"), "五年后端经验，负责支付系统。");
    await user.click(within(dialog).getByRole("button", { name: "确认复核并入库" }));
    expect(await within(dialog).findByText("资料不足，请补充摘要")).toBeVisible();
    expect(approved).toBe(false);
    expect(within(dialog).getByLabelText("复核摘要")).toHaveValue("五年后端经验，负责支付系统。");
    await user.click(within(dialog).getByRole("button", { name: "确认复核并入库" }));
    expect(await within(dialog).findByText("复核已通过")).toBeVisible();
    expect(submissions[1]).toMatchObject({ name: "已确认姓名", skills: ["Python", "Go"], summary: "五年后端经验，负责支付系统。" });
    await user.click(within(dialog).getByRole("button", { name: "关闭" }));
    expect(screen.queryByRole("button", { name: "待复核" })).not.toBeInTheDocument();
  });


  test("reopens a newly created case from its original match result", async () => {
    const fixture = recruitmentFixture();
    fixture.api.listJds = async () => [{ jd_id: "jd-1", revision_id: "rev-1", company: "金融公司", title: "后端", status: "READY", jd_status: "OPEN", ai_category: null, location: null, min_years: null, parsed_data: null, source_text: null }];
    const match = fixture.api.matchJd;
    fixture.api.matchJd = async (...args) => { const response = await match(...args); return { ...response, items: response.items.map((item) => ({ ...item, result_id: "result-1" })) }; };
    let created = 0;
    fixture.api.createCaseFromMatchResult = async () => { created += 1; return { case_id: "case-1", result_id: "result-1", status: "保留" }; };
    const user = userEvent.setup();
    render(<App api={fixture.api} />);
    await user.click(screen.getByText("JD 管理"));
    await user.click(await screen.findByRole("button", { name: "匹配" }));
    await user.click(screen.getByRole("button", { name: "建流程" }));
    await user.click(within(await screen.findByRole("dialog", { name: "招聘流程" })).getByRole("button", { name: "关闭" }));
    await user.click(screen.getByRole("button", { name: "查看流程" }));
    expect(await screen.findByRole("dialog", { name: "招聘流程" })).toBeVisible();
    expect(created).toBe(1);
  });

  test("shows final snapshot and closed-job controls without allowing accidental advancement", async () => {
    const fixture = recruitmentFixture();
    fixture.detail.process_rounds = [{ round_no: 1, round_name: "终面" }];
    fixture.detail.can_advance = false;
    fixture.detail.blocked_reason = "岗位已关闭";
    const user = userEvent.setup();
    render(<App api={fixture.api} />);
    const dialog = await openRecruitment(user);
    expect(within(dialog).getByText("岗位已关闭")).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: "通过进下一轮" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "通过（结束面试）" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "作废面试结果 pending" })).toBeEnabled();
    expect(within(dialog).getAllByText("2026/8/30 08:00:00（上海）")).toHaveLength(3);
  });

  test("reopens an existing case after closing its drawer", async () => {
    const fixture = recruitmentFixture();
    const user = userEvent.setup();
    render(<App api={fixture.api} />);
    let dialog = await openRecruitment(user);
    expect(within(dialog).getByText("第1轮 · 终面")).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: "关闭" }));
    fixture.detail.note = "下周继续跟进";
    await user.click(screen.getByRole("button", { name: "查看流程" }));
    dialog = await screen.findByRole("dialog", { name: "招聘流程" });
    expect(within(dialog).getByText("下周继续跟进")).toBeVisible();
  });

  test("resolves pending feedback with a final pass without creating another round", async () => {
    const fixture = recruitmentFixture();
    const user = userEvent.setup();
    render(<App api={fixture.api} />);
    const dialog = await openRecruitment(user);
    selectTime(dialog);
    await user.click(within(dialog).getByRole("button", { name: "通过（结束面试）" }));
    await waitFor(() => expect(within(dialog).getByLabelText("第1轮当前结果")).toHaveTextContent("通过"));
    expect(fixture.detail.rounds).toHaveLength(1);
    expect(fixture.detail.events.filter((e) => e.event_type === "INTERVIEW_RESULT").map((e) => e.result)).toEqual(["待反馈", "通过"]);
  });

  test("uses the newest effective result and restores actions after that result is voided", async () => {
    const fixture = recruitmentFixture();
    fixture.detail.events.push(fixture.event("passed", "INTERVIEW_RESULT", "通过", "2026-08-31T00:00:00Z"));
    fixture.detail.events.unshift({ ...fixture.event("void-fail", "INTERVIEW_RESULT", "未通过", "2026-09-01T00:00:00Z"), status: "void" });
    const user = userEvent.setup();
    render(<App api={fixture.api} />);
    const dialog = await openRecruitment(user);
    expect(within(dialog).getByLabelText("第1轮当前结果")).toHaveTextContent("通过");
    expect(within(dialog).queryByRole("button", { name: "通过（结束面试）" })).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "作废面试结果 passed" }));
    selectTime(dialog);
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "通过（结束面试）" })).toBeEnabled());
    expect(within(dialog).getByLabelText("第1轮当前结果")).toHaveTextContent("待反馈");
  });

  test("hides voided entries from the timeline and offers no result actions", async () => {
    const fixture = recruitmentFixture();
    fixture.detail.events.find((e) => e.id === "entered")!.status = "void";
    const user = userEvent.setup();
    render(<App api={fixture.api} />);
    const dialog = await openRecruitment(user);
    expect(within(dialog).getByLabelText("第1轮当前结果")).toHaveTextContent("待反馈");
    expect(within(dialog).queryByRole("button", { name: "通过（结束面试）" })).not.toBeInTheDocument();
    selectTime(dialog);
    expect(within(dialog).getByRole("button", { name: "进入面试" })).toBeEnabled();
  });

  test("blocks duplicate clicks and reuses the same request identity after uncertain failure", async () => {
    const fixture = recruitmentFixture();
    const bodies: unknown[] = [];
    let rejectFirst!: (error: Error) => void;
    fixture.api.recordResult = async (...args) => {
      bodies.push(args[3]);
      if (bodies.length === 1) await new Promise<void>((_resolve, reject) => { rejectFirst = reject; });
      const next = fixture.event("passed", "INTERVIEW_RESULT", args[2], "2026-08-31T03:00:00Z");
      fixture.detail.events.push(next);
      return next;
    };
    const user = userEvent.setup();
    render(<App api={fixture.api} />);
    const dialog = await openRecruitment(user);
    fireEvent.change(within(dialog).getByLabelText("发生时间（上海）"), { target: { value: "2026-08-30T15:30" } });
    await user.type(within(dialog).getByLabelText("操作备注"), "电话确认");
    const pass = within(dialog).getByRole("button", { name: "通过（结束面试）" });
    await user.dblClick(pass);
    expect(pass).toBeDisabled();
    expect(bodies).toHaveLength(1);
    await act(async () => rejectFirst(new Error("响应中断")));
    await user.click(within(dialog).getByRole("button", { name: "重试上次操作" }));
    await waitFor(() => expect(within(dialog).getByLabelText("第1轮当前结果")).toHaveTextContent("通过"));
    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toEqual(bodies[0]);
    expect(bodies[0]).toMatchObject({ occurred_at: "2026-08-30T15:30:00+08:00", note: "电话确认", idempotency_key: expect.any(String) });
  });

  test("uses one applied company, JD and date scope for every dashboard view and export", async () => {
    const api = fakeApi();
    const scopes: Record<string, unknown> = {};
    api.listJds = async () => [{ jd_id: "jd-finance", revision_id: "rev-1", company: "金融公司", title: "后端", status: "READY", jd_status: "OPEN", ai_category: null, location: null, min_years: null, parsed_data: null, source_text: null }];
    api.dashboardOverview = async (filters) => {
      scopes.overview = filters;
      return { recommendation_total: filters?.company === "金融公司" ? 7 : 99, offer_total: 1, active_offer_total: 1, onboarded_total: 0, candidate_total: 2, monthly_new_candidates: [] };
    };
    api.dashboardByJd = async (filters) => { scopes.byJd = filters; return []; };
    api.dashboardTrend = async (_granularity, filters) => { scopes.trend = filters; return []; };
    api.dashboardExport = async (filters) => { scopes.export = filters; };
    const user = userEvent.setup();
    render(<App api={api} />);
    await user.click(screen.getByText("数据看板"));
    await user.selectOptions(await screen.findByLabelText("看板公司"), "金融公司");
    await user.selectOptions(screen.getByLabelText("看板岗位"), "jd-finance");
    fireEvent.change(screen.getByLabelText("开始日期"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("结束日期"), { target: { value: "2026-08-31" } });
    await user.click(screen.getByRole("button", { name: "应用筛选" }));
    expect(await screen.findByText("7", { selector: "strong" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("开始日期"), { target: { value: "2026-08-20" } });
    await user.click(screen.getByRole("button", { name: "周" }));
    await user.click(screen.getByRole("button", { name: "导出 Excel" }));
    const expected = { company: "金融公司", jd_id: "jd-finance", date_from: "2026-08-01", date_to: "2026-08-31" };
    expect(scopes).toEqual({ overview: expected, byJd: expected, trend: expected, export: expected });
  });
});



function fakeApi(): RecruitmentApi {
  return {
    importResume: async () => ({
      candidate_id: "candidate-1",
      document_id: "document-1",
      revision_id: "revision-1",
      blob_id: "blob-1",
      task_id: "task-1"
    }),
    importFolder: async () => ({ imported: [], skipped: [], errors: [] }),
    getTask: async () => ({
      id: "task-1",
      task_type: "PARSE_RESUME",
      status: "SUCCESS",
      progress: 100,
      error_message: null
    }),
    listTasks: async () => [],
    controlTask: async (_taskId, action) => ({
      id: "task-1",
      task_type: "PARSE_RESUME",
      status: action === "pause" ? "PAUSED" : "QUEUED",
      progress: 20,
      error_message: null
    }),
    listResumeRevisions: async () => [],
    downloadResume: async () => undefined,
    previewResume: async () => "blob:preview",
    listCandidates: async () => [],
    listJds: async () => [],
    updateCandidateField: async (candidateId, field, value) => ({ candidate_id: candidateId, revision_id: "revision-1", field, value }),
    switchResumeRevision: async (revisionId) => ({
      revision_id: revisionId,
      display_name: "候选人",
      original_filename: "resume.pdf",
      status: "READY",
      is_current: true,
      created_at: "2026-08-30T00:00:00Z",
      parsed_data: null
    }),
    reparseResume: async (revisionId) => ({ revision_id: revisionId, task_id: "task-1" }),
    getResumeReview: async (revisionId) => ({ revision_id: revisionId, status: "READY", review_required: false, raw_text: "", parsed_data: null, review_data: null, manual_overrides: {}, extraction_diagnostics: {}, error_code: null, error_message: null }),
    approveResumeReview: async (revisionId, fields) => ({ revision_id: revisionId, status: "READY", review_required: false, raw_text: "", parsed_data: fields, review_data: null, manual_overrides: fields, extraction_diagnostics: {}, error_code: null, error_message: null }),
    indexStatus: async () => ({ pending: 0, failed: 0, items: [] }),
    retryIndexSync: async () => ({ pending: 0, failed: 0, items: [] }),
    searchCandidates: async () => ({
      items: [
        {
          candidate_id: "candidate-1",
          revision_id: "revision-1",
          name: "张三",
          phone: null,
          reasons: [],
          parsed_data: null,
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
    importJdFile: async () => ({ jd_id: "jd-file-1", revision_id: "rev-file-1" }),
    importJdBatch: async () => ({ imported: [{ jd_id: "jd-1", revision_id: "rev-1" }] }),
    importJdBatchFile: async () => ({ imported: [{ jd_id: "jd-file-1", revision_id: "rev-file-1" }] }),
    matchJd: async () => ({
      run_id: "run-1",
      items: [
        {
          candidate_id: "candidate-1",
          revision_id: "revision-1",
          name: "张三",
          phone: null,
          reasons: [],
          parsed_data: null,
          content: "张三 Python 金融风控",
          score: 0.95,
          matched_channels: ["bm25", "vector"],
          total_years: 6,
          highest_degree: "MASTER",
          location: "上海"
        }
      ]
    }),
    matchBatch: async (revisionIds) => ({
      results: revisionIds.map((revisionId) => ({
        revision_id: revisionId,
        run_id: `run-${revisionId}`,
        items: []
      }))
    }),
    markMatchResult: async (resultId, status) => ({ result_id: resultId, status }),
    listMatchResults: async () => ({ groups: [] }),
    listMatchResultsForCandidate: async () => [],
    matchCandidate: async () => [],
    createCaseFromMatchResult: async (resultId) => ({ case_id: "case-1", result_id: resultId, status: "保留" }),
    updateJdStatus: async (jdId, status) => ({ jd_id: jdId, status }),
    updateJdField: async (jdId, field, value) => ({ jd_id: jdId, revision_id: "rev-1", field, value }),
    exportMatchJd: async () => undefined,
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
    exportDiagnostics: async () => undefined,
    listMappingProjects: async () => [],
    createMappingProject: async (name: string) => ({ id: "proj-1", name, description: null }),
    buildMappingTree: async () => ({ id: "snap-1", label: "v1", is_current: true }),
    listMappingSnapshots: async () => [],
    getMappingTree: async () => [],
    searchBdLeads: async () => [],
    searchLeadsForCandidate: async () => [],
    updateLeadStatus: async () => ({ id: "lead-1", source: "web", company_name: "某公司", job_title: null, raw_snippet: null, url: null, status: "已联系" }),
    runBdAgent: async () => ({ session_id: "session-1", leads: [] }),
    runBdAgentStream: async () => ({ session_id: "session-1", leads: [] }),
    followUpBdAgent: async () => ({ session_id: "session-1", leads: [] }),
    createCase: async () => ({ id: "case-1", candidate_id: "candidate-1", jd_id: "jd-1", stage: "待评估", note: null }),
    listCases: async () => [],
    getCase: async () => ({
      id: "case-1",
      candidate_id: "candidate-1",
      jd_id: "jd-1",
      stage: "待评估",
      note: null,
      rounds: [],
      events: []
    }),
    recommendCase: async () => ({ id: "evt-1", event_type: "RECOMMENDED", case_round_id: null, round_name: null, occurred_at: "2026-08-31T00:00:00Z", recorded_at: "2026-08-31T00:00:00Z", result: null, note: null, status: "active" }),
    enterInterview: async () => ({ id: "evt-2", event_type: "INTERVIEW_ENTERED", case_round_id: "round-1", round_name: "第1轮", occurred_at: "2026-08-31T00:00:00Z", recorded_at: "2026-08-31T00:00:00Z", result: null, note: null, status: "active" }),
    recordResult: async () => ({ id: "evt-3", event_type: "INTERVIEW_RESULT", case_round_id: "round-1", round_name: "第1轮", occurred_at: "2026-08-31T00:00:00Z", recorded_at: "2026-08-31T00:00:00Z", result: "通过", note: null, status: "active" }),
    passAndAdvance: async () => [],
    offerCase: async () => ({ id: "evt-4", event_type: "OFFER", case_round_id: null, round_name: null, occurred_at: "2026-08-31T00:00:00Z", recorded_at: "2026-08-31T00:00:00Z", result: "已发放", note: null, status: "active" }),
    onboardCase: async () => ({ id: "evt-5", event_type: "ONBOARDED", case_round_id: null, round_name: null, occurred_at: "2026-08-31T00:00:00Z", recorded_at: "2026-08-31T00:00:00Z", result: null, note: null, status: "active" }),
    exitCase: async () => ({ id: "evt-6", event_type: "EXIT", case_round_id: null, round_name: null, occurred_at: "2026-08-31T00:00:00Z", recorded_at: "2026-08-31T00:00:00Z", result: null, note: null, status: "active" }),
    voidEvent: async () => ({ deleted: "evt-1" }),
    dashboardOverview: async () => ({
      recommendation_total: 1,
      offer_total: 1,
      active_offer_total: 1,
      onboarded_total: 0,
      candidate_total: 2,
      monthly_new_candidates: [{ month: "2026-08", count: 2 }]
    }),
    dashboardByJd: async () => [],
    dashboardTrend: async () => [],
    dashboardExport: async () => undefined,
    reverseMatch: async () => [],
    getCandidateContact: async () => ({ email: "zhang@example.com", phone: "13800138000", email_confidence: 0.9, phone_confidence: 0.9 }),
    updateCandidateContact: async (_candidateId, input) => ({ email: input.email, phone: input.phone, email_confidence: 1.0, phone_confidence: 1.0 }),
    listDeleted: async () => [],
    softDelete: async (entityType, entityId) => ({ entity_type: entityType, entity_id: entityId, deleted: true }),
    restoreDeleted: async () => ({ entity_type: "candidate", entity_id: "candidate-1", deleted: false }),
    applyCorrection: async (input) => ({
      correction_id: "correction-1",
      entity_type: input.entityType,
      field_name: input.fieldName,
      old_value: "张三",
      new_value: input.newValue,
      reverted: false
    }),
    undoCorrection: async () => ({
      correction_id: "correction-1",
      entity_type: "candidate",
      field_name: "display_name",
      old_value: "张三",
      new_value: "张四",
      reverted: true
    }),
    exportMappingTree: async () => undefined,
    exportMappingTreePdf: async () => undefined,
    listCompanies: async () => [],
    createCompany: async (name: string) => ({ id: "company-1", name }),
    updateCompany: async (companyId: string, name: string) => ({ id: companyId, name }),
    listDepartments: async () => [],
    createDepartment: async (input) => ({ id: "dept-1", company_id: input.company_id, parent_id: input.parent_id ?? null, name: input.name, leader_id: null, leader_report_to: null, team_size: null, business_direction: null, tech_stack: null, office_location: null, hc_status: null, hc_internal_note: null }),
    listEmployees: async () => [],
    createEmployee: async (input) => ({ id: "emp-1", company_id: input.company_id, department_id: input.department_id ?? null, name: input.name, title: input.title ?? null, job_level: input.job_level ?? null, report_to: input.report_to ?? null, subordinate_count: null, tenure_years: null, business_module: null, status: null, intention: null, remark: null, contact: null, is_key: input.is_key ?? false }),
    getOrgTree: async () => ({ id: "company-1", kind: "company", name: "字节跳动", title: null, job_level: null, team_size: null, is_key: false, children: [] }),
    exportOrgInternal: async () => undefined,
    exportOrgClient: async () => undefined,
    exportOrgArchPdf: async () => undefined,
    updateDepartment: async (departmentId, changes) => ({ id: departmentId, company_id: "company-1", parent_id: null, name: changes.name ?? "部门", leader_id: null, leader_report_to: null, team_size: null, business_direction: null, tech_stack: null, office_location: null, hc_status: null, hc_internal_note: null }),
    deleteDepartment: async () => undefined,
    updateEmployee: async (employeeId, changes) => ({ id: employeeId, company_id: "company-1", department_id: null, name: changes.name ?? "人员", title: null, job_level: null, report_to: null, subordinate_count: null, tenure_years: null, business_module: null, status: null, intention: null, remark: null, contact: null, is_key: false }),
    deleteEmployee: async () => undefined,
    deleteCompany: async () => undefined,
    getSettings: async () => ({}),
    updateSettings: async () => ({}),
    exportMatchRun: async () => undefined,
    listBackups: async () => [],
    createBackup: async () => ({ filename: "backup_1.sqlite3", path: "/tmp/backup_1.sqlite3" }),
    restoreBackup: async () => ({ restored_from: "backup_1.sqlite3", safety_backup: "/tmp/safety.sqlite3" }),
    createPortableBackup: async (targetPath) => ({ path: targetPath, same_volume: false }),
    restorePortableBackup: async (_backupPath, targetRoot) => ({ target_root: targetRoot, files_restored: 3, files_verified: 3, ok: true }),
    listReminders: async () => [],
    createReminder: async () => ({ id: "reminder-1", title: "跟进", note: null, remind_at: "2026-08-29T09:00:00", dismissed: false, dismissed_at: null }),
    dismissReminder: async () => ({ id: "reminder-1", title: "跟进", note: null, remind_at: "2026-08-29T09:00:00", dismissed: true, dismissed_at: "2026-08-29T10:00:00" }),
    migrateData: async () => ({ target_root: "/tmp/new", files_copied: 3, files_verified: 3, candidate_count: 1, ok: true }),
    setDataRoot: async (path: string) => path,
    onboardingStatus: async () => ({ data_root: "/tmp/data", llm_enabled: false, search_enabled: false, bd_search_enabled: false, mail_enabled: false, smtp_enabled: false, health: { database: { status: "healthy" } } }),
    testProviders: async () => [{ name: "llm", ok: true, message: "可用" }]
  };
}


describe("desktop recruitment workflow", () => {
  test("refreshes the candidate list after a single resume finishes parsing", async () => {
    const api = fakeApi();
    let listCalls = 0;
    api.listCandidatesPage = async () => {
      listCalls += 1;
      const items = listCalls === 1 ? [] : [{ candidate_id: "candidate-1", revision_id: "revision-1",
        display_name: "上传后候选人", total_years: 5, highest_degree: "BACHELOR",
        location: "上海", status: "AVAILABLE", revision_status: "READY", phone: null,
        original_filename: "resume.pdf", parsed_data: null }];
      return { items, total: items.length, page: 1, page_size: 100, has_more: false };
    };
    const user = userEvent.setup();
    render(<App api={api} />);
    await user.upload(
      screen.getByLabelText("选择简历文件"),
      new File(["resume"], "resume.pdf", { type: "application/pdf" }),
    );
    expect(await screen.findByText("上传后候选人")).toBeVisible();
  });

  test("submits explicit search filters and pages the bounded candidate list", async () => {
    const api = fakeApi();
    let receivedFilters: unknown;
    api.searchCandidates = async (_query, filters) => {
      receivedFilters = filters;
      return { items: [], degraded_reasons: [] };
    };
    const pages: number[] = [];
    api.listCandidatesPage = async (page, pageSize) => {
      pages.push(page);
      return { items: [{ candidate_id: `candidate-${page}`, revision_id: `revision-${page}`,
        display_name: `第${page}页候选人`, total_years: 5, highest_degree: "BACHELOR",
        location: "上海", status: "AVAILABLE", revision_status: "READY", phone: null,
        original_filename: "resume.pdf", parsed_data: null }], total: 150, page, page_size: pageSize,
        has_more: page < 2 };
    };
    const user = userEvent.setup();
    render(<App api={api} />);
    await screen.findByText("第1页候选人");
    await user.click(screen.getByText("精确筛选"));
    await user.type(screen.getByLabelText("最低工作年限"), "5");
    await user.type(screen.getByLabelText("现居城市"), "上海、苏州");
    await user.type(screen.getByLabelText("意向城市"), "北京");
    await user.type(screen.getByLabelText("排除技能"), "外包");
    await user.type(screen.getByLabelText("人才搜索"), "Python");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    expect(receivedFilters).toEqual({ min_years: 5, locations: ["上海", "苏州"],
      preferred_locations: ["北京"], exclude_skills: ["外包"] });
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(await screen.findByText("第2页候选人")).toBeVisible();
    expect(pages).toEqual([1, 2]);
  });

  test("searches candidates and previews the resume", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.type(screen.getByPlaceholderText("搜索人才、技能、公司或自然语言"), "Python 金融");
    await user.click(screen.getByRole("button", { name: "搜索" }));

    expect(await screen.findByText("张三")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "查看详情" }));

    expect(await screen.findByRole("button", { name: "关闭" })).toBeVisible();
  });

  test("imports a JD and shows its revision id", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(screen.getByText("JD 管理"));
    await user.type(screen.getByLabelText("JD 原文"), "负责支付系统，3年 Java");
    await user.click(screen.getByRole("button", { name: "导入并解析" }));

    expect(await screen.findByText("rev-1")).toBeVisible();
  });

  test("imports a Word JD file", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(screen.getByText("JD 管理"));
    await user.upload(
      screen.getByLabelText("选择 JD 文件"),
      new File(["jd"], "后端工程师.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" })
    );

    expect(await screen.findByText("rev-file-1")).toBeVisible();
  });

  test("matches a JD and shows candidates in the drawer without shortlist marks", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    api.listJds = async () => [
      {
        jd_id: "jd-1",
        revision_id: "rev-1",
        company: "某金融",
        title: "Java 后端工程师",
        status: "READY",
        jd_status: "OPEN",
        ai_category: null,
        location: null,
        min_years: null,
        parsed_data: null,
        source_text: "Java 后端"
      }
    ];
    api.matchJd = async () => ({
      run_id: "run-1",
      items: [
        {
          candidate_id: "candidate-1",
          revision_id: "revision-1",
          name: "张三",
          phone: null,
          reasons: [],
          parsed_data: null,
          content: "张三 Python 金融风控",
          score: 0.95,
          matched_channels: ["bm25", "vector"],
          total_years: 6,
          highest_degree: "MASTER",
          location: "上海",
          result_id: "result-1"
        }
      ]
    });
    render(<App api={api} />);

    await user.click(screen.getByText("JD 管理"));
    await user.click(screen.getByRole("button", { name: "匹配" }));
    expect(await screen.findByText("张三")).toBeVisible();
    expect(screen.queryByRole("button", { name: "短名单" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "排除" })).not.toBeInTheDocument();
  });

  test("loads the recruitment dashboard", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(screen.getByText("数据看板"));
    await user.click(screen.getByRole("button", { name: "刷新看板" }));

    expect(await screen.findByText("推荐总数")).toBeVisible();
    expect(screen.getByText("offer 总数")).toBeVisible();
    expect(screen.getByText("每岗位每轮通过率")).toBeVisible();
  });

  test("creates a company in the mapping tab", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(screen.getByText("Mapping"));
    await user.type(screen.getByLabelText("公司名称"), "字节跳动");
    await user.click(screen.getByRole("button", { name: "新建公司" }));

    expect(await screen.findByText("字节跳动")).toBeVisible();
  });

  test("searches BD leads and shows empty state", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(screen.getByText("BD 助手"));
    await user.type(screen.getByLabelText("BD 深度检索"), "Java 工程师");
    await user.click(screen.getByRole("button", { name: "深度检索" }));

    expect(await screen.findByText("暂无线索")).toBeVisible();
  });

  test("tests configured providers and explains when saved settings apply", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(screen.getByText("设置"));
    await user.click(screen.getByRole("button", { name: "测试 API" }));
    expect(await screen.findByText("大模型：可用")).toBeVisible();

    await user.type(screen.getByLabelText("DeepSeek API Key"), "sk-test-key");
    await user.click(screen.getByRole("button", { name: "保存设置" }));
    expect(await screen.findByText("设置已保存，重启应用后生效")).toBeVisible();
  });
});
