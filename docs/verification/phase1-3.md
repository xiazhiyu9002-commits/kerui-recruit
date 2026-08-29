# Phase 1–3 交付与验收证据

**日期：** 2026-08-29
**依据：** `docs/superpowers/specs/2026-08-29-embedded-recruitment-desktop-design.md`

## 完成范围

Phase 1–3 的后端业务能力与前端主界面已实现并固化落库，覆盖：

- **JD 与匹配**：JD 文本/Word/Excel 导入与结构化解析、单 JD 匹配、批量 JD 匹配、反向匹配（以人找岗）、结果标记（收藏/短名单/排除）、`match_run` 快照与 Excel 导出。
- **招聘流程**：候选人-JD `case` 流程、阶段推进/撤销、事件链。
- **Mapping**：项目、缩进文本建树、快照、树 Excel/PDF 导出。
- **BD 助手**：以岗找公司、来源留痕、线索状态更新。
- **任务中心**：持久化任务租约、失败重试、取消、崩溃恢复。
- **运维**：备份/恢复、数据目录迁移（复制+哈希校验）、诊断包、健康检测（含磁盘与检索预热）、首次启动检查（数据目录/Provider 配置/健康汇总）。
- **数据安全**：字段级 AES-256-GCM 加密、软删除/回收站/恢复/30 天到期清理/撤销。
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
- **12 万候选人全量性能压测**（spec 7.3 / 12.2.3）：`python -m kerui_recruit.bench.search_benchmark --candidates 120000 --queries 800 --concurrency 10 --qps 5`，结果见 `docs/verification/phase0-benchmark-120k.json`：

| 指标 | 实测 | 目标 | 结果 |
| --- | --- | --- | --- |
| P95 | 436.9 ms | ≤ 1500 ms | ✅ |
| P99 | 459.21 ms | ≤ 2500 ms | ✅ |
| error_rate | 0.0 | 0 | ✅ |
| Recall@300 | 1.0 | ≥ 0.98 | ✅ |
| nDCG@10 | 0.865 | ≥ 0.85 | ✅ |

- **检索性能门槛**：`pytest tests/performance -m performance` 在 12,000 候选规模通过（p95 ≤ 1.5s、p99 ≤ 2.5s、Recall@300 ≥ 98%）。
- **便携备份**：`PortableBackupService` 将 db / search / blobs / config 打包为单一 `.krbackup`（含 SHA-256 清单），用口令派生密钥（PBKDF2-SHA256 + Fernet）加密，恢复到新目录并逐文件校验哈希（`tests/backup/test_portable_backup.py`，含错误口令拒绝测试）。
- **自动增量备份**：后台调度器每日生成 SQLite 快照并按「7 每日 + 4 每周」轮换清理（`BackupService.prune` + `SchedulerService.backup_tick`）。
- **脱敏样本端到端验收**（spec 12.2.4）：`tests/api/test_full_acceptance.py` 用脱敏简历样本走通 解析 → 去重（Blob 复用）→ 搜索 → JD 匹配 → Excel 导出 全链路。
- **浏览器端 E2E**（spec 12.1）：`npm run test:e2e`（Playwright + 本地 sidecar + vite）**6 全部通过**，覆盖简历导入/检索、JD 导入/匹配、看板、Mapping、BD、健康检测与备份。为此修复了 sidecar CORS、`fetch` 绑定、后台任务轮询与健康标签本地化。

## 尚未在本机闭环的验收项

以下项依赖外部资源或专用构建机，代码与脚本已就绪但需在目标环境执行：

1. **代码签名与 macOS 安装包**（spec 11）：Windows NSIS 安装包已构建（未签名）；代码签名需证书。macOS arm64 需在 Apple Silicon 构建机执行 `npm run tauri build`，不可交叉打包。

2. **真实样本验收**（spec 12.2.4）：脱敏样本全链路已通过；真实招聘简历样本（含真实姓名/联系方式）需在用户侧跑通，覆盖扫描件 OCR 与字段校验。

## CI

`.github/workflows/ci.yml` 提供 Windows 基线：后端 `pytest` + 桌面 `tsc -b` / `npm test`。macOS 构建与签名、安装/升级/卸载、路径/休眠/磁盘满等专项测试需在对应 CI 运行器补充。
