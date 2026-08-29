import { describe, expect, test } from "vitest";

import { ApiClient } from "../src/api/client";


describe("ApiClient", () => {
  test("adds the per-launch session token to JSON requests", async () => {
    let received: Request | undefined;
    const fetcher: typeof fetch = async (input, init) => {
      received = new Request(input, init);
      return new Response(JSON.stringify({ items: [], degraded_reasons: [] }), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    };
    const client = new ApiClient("http://127.0.0.1:43127", "launch-token", fetcher);

    await client.searchCandidates("Python 金融");

    expect(received?.url).toBe("http://127.0.0.1:43127/api/search/candidates");
    expect(received?.headers.get("X-Kerui-Session")).toBe("launch-token");
    expect(await received?.json()).toEqual({ query: "Python 金融", limit: 50 });
  });

  test("lets the browser set the multipart upload boundary", async () => {
    let received: Request | undefined;
    let suppliedHeaders: Headers | undefined;
    const fetcher: typeof fetch = async (input, init) => {
      suppliedHeaders = new Headers(init?.headers);
      received = new Request(input, init);
      return new Response(JSON.stringify({
        candidate_id: "candidate-1",
        document_id: "document-1",
        revision_id: "revision-1",
        blob_id: "blob-1",
        task_id: "task-1"
      }), { headers: { "Content-Type": "application/json" }, status: 200 });
    };
    const client = new ApiClient("http://127.0.0.1:43127", "launch-token", fetcher);

    await client.importResume(new File(["resume"], "resume.pdf", { type: "application/pdf" }));

    expect(received?.body).not.toBeNull();
    expect(suppliedHeaders?.has("Content-Type")).toBe(false);
  });

  test("surfaces the stable Chinese API error message", async () => {
    const fetcher: typeof fetch = async () => new Response(JSON.stringify({
      code: "E_FILE_TYPE_UNSUPPORTED",
      message: "仅支持 PDF、DOC 和 DOCX 简历",
      request_id: "request-1",
      details: null
    }), { headers: { "Content-Type": "application/json" }, status: 400 });
    const client = new ApiClient("http://127.0.0.1:43127", "launch-token", fetcher);

    await expect(client.importResume(new File(["x"], "resume.txt"))).rejects.toThrow(
      "仅支持 PDF、DOC 和 DOCX 简历"
    );
  });
});
