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

  test("diagnostics requests the correct path", async () => {
    let received: Request | undefined;
    const fetcher: typeof fetch = async (input, init) => {
      received = new Request(input, init);
      return new Response(JSON.stringify({
        sqlite_version: "3.45.3",
        database_path: "/tmp/db",
        database_size_bytes: 1024,
        counts: {},
        pragmas: {}
      }), { headers: { "Content-Type": "application/json" }, status: 200 });
    };
    const client = new ApiClient("http://127.0.0.1:43127", "launch-token", fetcher);

    await client.diagnostics();

    expect(received?.url).toBe("http://127.0.0.1:43127/api/diagnostics");
  });

  test("buildMappingTree posts text and label to the project", async () => {
    let received: Request | undefined;
    const fetcher: typeof fetch = async (input, init) => {
      received = new Request(input, init);
      return new Response(JSON.stringify({ id: "snap-1", label: "v1", is_current: true }), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    };
    const client = new ApiClient("http://127.0.0.1:43127", "launch-token", fetcher);

    await client.buildMappingTree("proj-1", "字节跳动\n  技术部", "v1");

    expect(received?.url).toBe("http://127.0.0.1:43127/api/mapping/projects/proj-1/build-from-text");
    expect(await received?.json()).toEqual({ text: "字节跳动\n  技术部", label: "v1" });
  });

  test("searchBdLeads posts query and limit", async () => {
    let received: Request | undefined;
    const fetcher: typeof fetch = async (input, init) => {
      received = new Request(input, init);
      return new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    };
    const client = new ApiClient("http://127.0.0.1:43127", "launch-token", fetcher);

    await client.searchBdLeads("Java 工程师", 20);

    expect(received?.url).toBe("http://127.0.0.1:43127/api/bd/search");
    expect(await received?.json()).toEqual({ query: "Java 工程师", limit: 20 });
  });

  test("provider connectivity uses the onboarding probe endpoint", async () => {
    let received: Request | undefined;
    const fetcher: typeof fetch = async (input, init) => {
      received = new Request(input, init);
      return new Response(JSON.stringify([{ name: "llm", ok: true, message: "可用" }]), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    };
    const client = new ApiClient("http://127.0.0.1:43127", "launch-token", fetcher);

    await client.testProviders();

    expect(received?.url).toBe("http://127.0.0.1:43127/api/onboarding/test-providers");
    expect(received?.method).toBe("POST");
  });

  test("lists tasks and posts task control actions", async () => {
    const received: Request[] = [];
    const fetcher: typeof fetch = async (input, init) => {
      received.push(new Request(input, init));
      return new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    };
    const client = new ApiClient("http://127.0.0.1:43127", "launch-token", fetcher);

    await client.listTasks();
    await client.controlTask("task/1", "pause");

    expect(received[0].url).toBe("http://127.0.0.1:43127/api/tasks");
    expect(received[0].method).toBe("GET");
    expect(received[1].url).toBe("http://127.0.0.1:43127/api/tasks/task%2F1/pause");
    expect(received[1].method).toBe("POST");
  });

  test("imports JD files and switches resume revisions", async () => {
    const received: Request[] = [];
    const fetcher: typeof fetch = async (input, init) => {
      received.push(new Request(input, init));
      const payload = received.length === 1
        ? { jd_id: "jd-1", revision_id: "jd-rev-1" }
        : { revision_id: "resume-rev-1", original_filename: "resume.pdf", status: "READY", is_current: true, created_at: "2026-08-30T00:00:00Z" };
      return new Response(JSON.stringify(payload), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    };
    const client = new ApiClient("http://127.0.0.1:43127", "launch-token", fetcher);

    await client.importJdFile(new File(["jd"], "岗位.docx"), "某公司", "后端工程师");
    await client.switchResumeRevision("resume/rev-1");

    expect(received[0].url).toBe("http://127.0.0.1:43127/api/jd/import-file");
    expect(received[0].method).toBe("POST");
    expect(received[0].headers.get("Content-Type")).toMatch(/^multipart\/form-data; boundary=/);
    expect(received[1].url).toBe("http://127.0.0.1:43127/api/resumes/revisions/resume%2Frev-1/switch");
    expect(received[1].method).toBe("POST");
  });

  test("posts batch matches and result marks", async () => {
    const received: Request[] = [];
    const fetcher: typeof fetch = async (input, init) => {
      received.push(new Request(input, init));
      return new Response(JSON.stringify(received.length === 1
        ? { results: [] }
        : { result_id: "result-1", status: "短名单" }), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    };
    const client = new ApiClient("http://127.0.0.1:43127", "launch-token", fetcher);

    await client.matchBatch(["rev-1", "rev-2"], 30);
    await client.markMatchResult("result/1", "短名单");

    expect(received[0].url).toBe("http://127.0.0.1:43127/api/match/batch");
    expect(await received[0].json()).toEqual({ revision_ids: ["rev-1", "rev-2"], limit: 30 });
    expect(received[1].url).toBe("http://127.0.0.1:43127/api/match/result/result%2F1/mark");
    expect(await received[1].json()).toEqual({ status: "短名单" });
  });

  test("posts portable backup and restore requests", async () => {
    const received: Request[] = [];
    const fetcher: typeof fetch = async (input, init) => {
      received.push(new Request(input, init));
      return new Response(JSON.stringify(received.length === 1
        ? { path: "D:/backup.krbackup", same_volume: false }
        : { target_root: "D:/restored", files_restored: 2, files_verified: 2, ok: true }), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    };
    const client = new ApiClient("http://127.0.0.1:43127", "launch-token", fetcher);

    await client.createPortableBackup("D:/backup.krbackup", "passphrase");
    await client.restorePortableBackup("D:/backup.krbackup", "D:/restored", "passphrase");

    expect(received[0].url).toBe("http://127.0.0.1:43127/api/backup/portable");
    expect(await received[0].json()).toEqual({ target_path: "D:/backup.krbackup", passphrase: "passphrase" });
    expect(received[1].url).toBe("http://127.0.0.1:43127/api/backup/portable/restore");
    expect(await received[1].json()).toEqual({ backup_path: "D:/backup.krbackup", target_root: "D:/restored", passphrase: "passphrase" });
  });

  test("posts soft delete and auditable corrections", async () => {
    const received: Request[] = [];
    const fetcher: typeof fetch = async (input, init) => {
      received.push(new Request(input, init));
      return new Response(JSON.stringify(received.length === 1
        ? { entity_type: "candidate", entity_id: "candidate-1", deleted: true }
        : { correction_id: "correction-1", entity_type: "candidate", field_name: "display_name", old_value: "张三", new_value: "张四", reverted: false }), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    };
    const client = new ApiClient("http://127.0.0.1:43127", "launch-token", fetcher);

    await client.softDelete("candidate", "candidate-1");
    await client.applyCorrection({
      entityType: "candidate",
      entityId: "candidate-1",
      fieldName: "display_name",
      newValue: "张四",
      reason: "姓名纠正"
    });

    expect(received[0].url).toBe("http://127.0.0.1:43127/api/soft-delete");
    expect(await received[0].json()).toEqual({ entity_type: "candidate", entity_id: "candidate-1" });
    expect(received[1].url).toBe("http://127.0.0.1:43127/api/correction/apply");
    expect(await received[1].json()).toEqual({ entity_type: "candidate", entity_id: "candidate-1", field_name: "display_name", new_value: "张四", reason: "姓名纠正" });
  });
});
