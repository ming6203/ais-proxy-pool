# 变更记录

## v1.1.0 — 2026-11-27

跟进前置补丁新基线，功能不变：

- 基线更新为原项目 `c770aaf3c76a10dbcd6584d033bb76ffa80ccd27` + `ais-pg-upgrade` release `20261126-c770-compat`（`d486455`）。
- `account_service.py`：合并新版 Cookie 轮换的并发锁 / 429 退避逻辑，并在两处 `rotate_google_cookies` 调用上保留按账号代理。
- `config.py`：不再携带与代理池无关的重构改动，直接使用上游版本。
- `cookie_parser.py`、`signer.py`、`waa-signer/main.go` 及其测试按新上游重新应用（`__Host-GAPS` 白名单、`encode_wire_base64_str` 改名、`mergeRecreatedState` 均保留）。
- 前端重新构建：资源哈希与 v1.0.0 完全一致（上游与前置补丁未改动 web），仅 `index.html` 有一处空白差异。
- 清单共 55 条变更（45 写 / 10 删），release_id `20261127-proxy-pool-c770-b6e5b4f0`。
- 验证：873 项 pytest、Go 签名器测试、`check → apply → rollback` 全通过。

## v1.0.0 — 2026-11-27

首个版本：

- 基线：原项目 `a28a6c5b0790c4efa4495de8393631bf1ae814b1` + `ais-pg-upgrade` release `20261123-full-reply-tools-8c371879`。
- 命名代理池（`data/proxies.json`）、一号一代理、未绑定即直连、删除自动解绑。
- 启动时把旧 `config.yaml network.proxy` 与账号单格代理 URL 迁入代理池。
- 安装器支持 `check` / `apply` / `rollback`，前置补丁与安装状态检查、路径白名单、失败自动恢复。