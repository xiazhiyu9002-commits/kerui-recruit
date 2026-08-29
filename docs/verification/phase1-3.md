# Phase 1–3 交付与验收证据

**日期：** 2026-08-29
**依据：** `docs/superpowers/specs/2026-08-29-embedded-recruitment-desktop-design.md`

## 完成范围

Phase 1–3 的后端业务能力与前端主界面已实现并固化落库，覆盖：

- **JD 与匹配**：JD 文本导入与结构化解析、单 JD 匹配、反向匹配（以人找岗）、`match_run` 快照与 Excel 导出。
- **招聘流程**：候选人-JD `case` 流程、阶段推进/撤销、事件链。
- **Mapping**：项目、缩进文本建树、快照、树导出。
- **BD 助手**：以岗找公司、来源留痕、线索状态更新。
- **运维**：备份/恢复、数据目录迁移（复制+哈希校验）、诊断包、健康检测（含磁盘与检索预热）。
- **数据安全**：字段级 AES-256-GCM 加密、软删除/回收站/撤销。
- **被动入库**：IMAP 邮箱附件过滤/游标/幂等、提醒与 SMTP 发送、调度器。
- **设置**：可配置 API 密钥（DeepSeek / 硅基流动 / Tavily / IMAP / SMTP），密钥脱敏存储。
- **OCR**：扫描件走 OpenAI-compatible 视觉模型 OCR Provider（未配置密钥时扫描件解析报 `E_OCR_REQUIRED`）。

## 自动化证据

| 层 | 命令 | 结果 |
| --- | --- | --- |
| 后端单元/集成 | `pytest -q`（`backend`，非 performance） | **137 passed** |
| 后端性能门槛 | `pytest tests/performance -m performance` | **1 passed**（12,000 候选、200 查询，p95 ≤ 1.5s、p99 ≤ 2.5s、Recall@300 ≥ 98%） |
| 桌面 React 单元 | `npm test`（`desktop`） | **14 passed** |
| 桌面类型检查 | `npx tsc -b`（`desktop`） | 通过 |
| 桌面 Rust 单元 | `cargo test`（`desktop/src-tauri`） | **2 passed** |
| 桌面 E2E | `npm run test:e2e`（需打包后的 Tauri 壳 + sidecar） | 见下方说明 |

后端覆盖 Provider 契约、SQLite schema、简历/JD/匹配/流程/Mapping/BD/备份/诊断/加密/提醒/调度/软删除/迁移等模块。

## 本机已验证的交付物

- **Windows NSIS 安装包**：`npm run tauri build -- --bundles nsis` 产出 `desktop/src-tauri/target/release/bundle/nsis/kerui-recruit-desktop_0.1.0_x64-setup.exe`（约 152 MB，含 PyInstaller sidecar 与 Tauri 壳）。sidecar 通过 `bundle.resources` 打入安装包，壳层经 `resolve_sidecar_binary` 从资源目录解析。
- **检索性能门槛**：`pytest tests/performance -m performance` 在 12,000 候选规模通过（p95 ≤ 1.5s、p99 ≤ 2.5s、Recall@300 ≥ 98%）。

## 尚未在本机闭环的验收项

以下项依赖外部资源或专用构建机，代码与脚本已就绪但需在目标环境执行：

1. **12 万候选人全量性能压测**（spec 7.3）：
   `python -m kerui_recruit.bench.search_benchmark --candidates 120000 --queries 800 --concurrency 10 --qps 5`
   验证 P95 ≤ 1.5s、P99 ≤ 2.5s、Recall@300 ≥ 98%、nDCG@10 ≥ 0.85（12,000 规模门槛已通过）。

2. **代码签名与 macOS 安装包**（spec 11）：Windows NSIS 安装包已构建（未签名）；代码签名需证书。macOS arm64 需在 Apple Silicon 构建机执行 `npm run tauri build`，不可交叉打包。

3. **浏览器端 E2E**（spec 12.1）：`search.spec.ts` 与 `workflow.spec.ts` 需打包后的 Tauri 壳与 sidecar 同机运行；本机已完成 sidecar HTTP 闭环、壳层启动/退出冒烟与安装包构建。

4. **真实/脱敏样本验收**（spec 12.2.4）：需真实简历样本走通解析、去重、版本、搜索、匹配、导出全链路。

5. **备份恢复一致性验证**（spec 12.2.5）：`BackupService` 已提供快照/恢复与安全备份，需在干净目录做恢复前后实体数量与 Blob 哈希比对。

## CI

`.github/workflows/ci.yml` 提供 Windows 基线：后端 `pytest` + 桌面 `tsc -b` / `npm test`。macOS 构建与签名、安装/升级/卸载、路径/休眠/磁盘满等专项测试需在对应 CI 运行器补充。
