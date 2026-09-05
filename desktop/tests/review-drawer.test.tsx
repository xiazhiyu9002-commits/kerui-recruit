import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ResumeReviewDrawer } from "../src/resumes/ResumeReviewDrawer";
import type { RecruitmentApi, ResumeReview } from "../src/App";
vi.mock("../src/resumes/DirectionEditor", () => ({ DirectionEditor: () => null }));
const initial: ResumeReview = { revision_id: "r", status: "PENDING_REVIEW", review_required: true, raw_text: "old text", parsed_data: null, review_data: { name: "old" }, manual_overrides: {}, extraction_diagnostics: {}, error_code: null, error_message: null };

test("protects unsaved fields when closing the review", () => {
  const close = vi.fn();
  render(<ResumeReviewDrawer api={{} as RecruitmentApi} initialReview={initial} onClose={close} onApproved={() => {}} />);
  fireEvent.change(screen.getByLabelText("复核姓名"), { target: { value: "edited" } });
  fireEvent.click(screen.getByText("关闭", { selector: "button" }));
  expect(close).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "放弃修改并关闭" }));
  expect(close).toHaveBeenCalledOnce();
});

test("awaits OCR completion and reloads the visible review evidence", async () => {
  let finish!: () => void;
  const work = new Promise<void>((resolve) => { finish = resolve; });
  const api = { getResumeReview: vi.fn(async () => ({ ...initial, raw_text: "new OCR text", review_data: { name: "new" } })) } as unknown as RecruitmentApi;
  render(<ResumeReviewDrawer api={api} initialReview={initial} onClose={() => {}} onApproved={() => {}} onForceReparse={() => work} />);
  fireEvent.click(screen.getByRole("button", { name: "强制OCR" }));
  expect(screen.getByRole("button", { name: "解析中…" })).toBeDisabled();
  await act(async () => finish());
  await waitFor(() => expect(screen.getByLabelText("复核姓名")).toHaveValue("new"));
  expect(screen.getByText("new OCR text")).toBeVisible();
});
