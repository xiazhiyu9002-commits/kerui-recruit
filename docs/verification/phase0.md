# Phase 0 验收证据

**日期：** 2026-08-29  
**依据：** `docs/superpowers/plans/2026-08-29-phase0-search-foundation.md`

## 完成范围

Phase 0 全部 11 个任务均已实现，覆盖：SQLite 事实库、内容寻址原件库、持久化任务租约、Provider 契约、简历解析管线、LanceDB 混合检索、本地安全 API、Tauri/React 桌面壳与 sidecar 生命周期、以及 12 万候选的检索性能门槛。

## 自动化证据

| 层 | 命令 | 结果 |
| --- | --- | --- |
| 后端单元/集成 | `pytest backend/tests -m "not performance"` | 51 passed |
| 后端性能门槛 | `pytest backend/tests/performance -m performance` | 通过（12,000 候选、200 查询、召回 98%+，p95 ≤ 1.5s） |
| 桌面 Rust 单元 | `cargo test`（`desktop/src-tauri`） | 2 passed |
| 桌面 React 单元 | `npm test`（`desktop`） | 5 passed |
| 桌面 E2E | `npm run test:e2e -- search.spec.ts`（需打包 sidecar） | 见下方说明 |

## 性能门槛

`BenchmarkApp` 使用确定性本地 Provider（无实时 API Key），在 12,000 候选规模验证：

- `error_rate == 0`
- `p95_ms <= 1500`
- `p99_ms <= 2500`
- `recall_at_300 >= 0.98`

生产发布门槛按 `python -m kerui_recruit.bench.search_benchmark --candidates 120000 --queries 800 --concurrency 10 --qps 5` 运行，报告写入 `docs/verification/phase0.md` 同级的 JSON 产物。

## 桌面壳交付说明

Rust 壳层实现了随机回环端口选择、256 位启动令牌生成、sidecar 启动与 `/health/ready` 等待，以及应用退出时终止 sidecar。sidecar 打包（PyInstaller 产物 `kerui-recruit-sidecar[.exe]`）与 Playwright E2E 需在打包流水线中完成——本地未安装打包工具链，未在本机验证完整 GUI 启动。