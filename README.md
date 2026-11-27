# aistudio-api 代理池升级包

在 [DeconstructedCube/aistudio-api](https://github.com/DeconstructedCube/aistudio-api) 上增加「命名代理池 + 一号一代理」能力的独立升级包，安装形态与 [Mooece/ais-pg-upgrade](https://github.com/Mooece/ais-pg-upgrade) 相同：只携带升级文件、清单和安装器，不包含原项目代码、Git 历史、配置、Cookie 或账号数据。

> **前置要求（必须）**：先完成原项目安装，再应用 `ais-pg-upgrade` 补丁，最后安装本升级包。安装器会检查原项目的 `.venv`、已编译的 `waa-signer`，以及本包所依赖的 `ais-pg-upgrade` 基线文件；任一条件不满足都会拒绝应用，不会代装任何东西。

## 功能

- **命名代理池**：在控制台「系统设置 → 代理池」中保存任意多个代理（名称 / 地址 / 备注），每个可单独测试连通性、编辑、删除；支持 HTTP / HTTPS / SOCKS5 / SOCKS5H，地址与凭据保存在 `data/proxies.json`，不写进 `config.yaml`，也不会被 git 跟踪。
- **一号一代理**：账号管理页每行可直接从代理池选择；「编辑账号」与「导入账号」同样支持。代理按账号独立生效：HTTP 连接池、WAA 签名、导入探活、等级/邮箱探测、Cookie 轮换全部走该账号绑定的出口。
- **未绑定即直连**：没有选择代理的账号直接连接，不受环境变量或系统代理影响（它们只用于模型发现等非账号流量）。
- **删除即解绑**：删除正在被账号使用的代理会提示，并把相关账号恢复为直连，不会留下悬空引用。
- **旧配置自动迁移**：启动时把旧版 `config.yaml` 的 `network.proxy`、旧账号上的单格代理 URL 转成命名代理并入池（名称形如 `迁移-全局代理`、`迁移-host:port`），随后清除旧字段。
- **失败可回滚**：应用前完整备份被修改文件，失败自动恢复；`rollback` 校验哈希后再还原。

## 基线（重要）

本升级包只适用于**已完成下列安装**的目录：

| 层级 | 来源 | 版本 |
|---|---|---|
| 原项目 | [DeconstructedCube/aistudio-api](https://github.com/DeconstructedCube/aistudio-api) | 提交 `a28a6c5b0790c4efa4495de8393631bf1ae814b1` |
| 前置补丁 | [Mooece/ais-pg-upgrade](https://github.com/Mooece/ais-pg-upgrade) | release `20261123-full-reply-tools-8c371879`（`bd8893d`），已 `apply` |
| 本升级包 | 本仓库 | 见 `patch-manifest.json` 的 `release_id` |

清单对每个被修改文件都记录了该基线的 SHA-256。若目标文件与基线不一致（例如先升级了 `ais-pg-upgrade`、手工改过代码或重新构建过前端），`check`/`apply` 会拒绝并指出冲突文件。

## 安装

### 0. 准备

- 原项目已按官方说明安装完成：存在 `.venv`（Python ≥ 3.11）与已编译的 `waa-signer/bin/waa-signer[.exe]`
- 已应用 `ais-pg-upgrade` 并成功启动过一次
- 本升级包与项目放在不同目录，例如 `D:\01Project\aistudio-api` 与 `D:\01Project\ais-proxy-pool`

> 应用前先停止服务并暂停自动重启。代码改动不会热加载，必须重启一个新的服务实例。

### 1. 拉取本仓库

```bash
git clone https://github.com/ming6203/ais-proxy-pool.git ais-proxy-pool
```

### 2. 检查并应用

Windows（PowerShell，路径替换为实际位置）：

```powershell
$project = 'D:\01Project\aistudio-api'
$addon   = 'D:\01Project\ais-proxy-pool'
& "$project\.venv\Scripts\python.exe" -B "$addon\upgrade.py" check --project $project
& "$project\.venv\Scripts\python.exe" -B "$addon\upgrade.py" apply --project $project
```

Linux / macOS / Termux：

```bash
project=$HOME/aistudio-api
addon=$HOME/ais-proxy-pool
"$project/.venv/bin/python" -B "$addon/upgrade.py" check --project "$project"
"$project/.venv/bin/python" -B "$addon/upgrade.py" apply --project "$project"
```

也可以直接使用封装脚本（Windows 会检查端口、应用后编译签名器并启动）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$addon\Upgrade-Windows.ps1" -ProjectPath $project -Port 8080
```

`apply` 会打印本次备份目录，请保存。`check` 通过后 `apply` 才可用；重复执行 `apply` 在已升级状态下不会改动文件。

### 3. 重新编译签名器（必须）

本升级包改动了 `waa-signer/cmd/waa-signer/main.go`，使签名器支持按请求的 `direct`（强制直连）语义。应用后必须重编：

```powershell
# Windows
powershell -NoProfile -ExecutionPolicy Bypass -File "$project\waa-signer\build.ps1"
```

```bash
# Linux / macOS / Termux
bash "$project/waa-signer/build.sh"
```

### 4. 启动并验证

按原方式启动 `start.bat` / `bash start.sh`，然后：

1. 打开 `http://localhost:8080/health`，应返回 `{"status":"ok"}`
2. 「系统设置」页应出现**代理池**卡片（不再有「网络与出口代理」或「网络代理状态」）
3. 「账号管理」页每行账号名旁出现代理下拉：`直连（不使用代理）` + 代理池中的命名代理
4. `GET http://localhost:8080/api/proxies` 返回 `[]` 或已有代理列表
5. 导入一个账号并绑定代理后，`GET /api/accounts` 中该账号的 `proxy_id` / `proxy_name` 应有值

## 回滚

先停止服务，然后用原项目 Python 执行：

```powershell
& "$project\.venv\Scripts\python.exe" -B "$addon\upgrade.py" rollback --backup '上面打印的备份目录'
```

回滚会校验目标与备份哈希，只还原本次升级涉及的文件；配置、Cookie、账号数据和依赖环境不受影响。回滚后请重新编译签名器（`waa-signer` 源码会一起还原），再按原方式启动。

## 更新与卸载

- 后续升级：先 `git pull --ff-only` 更新本仓库，再对原项目执行 `check` / `apply`
- 卸载：执行最后一次 `apply` 打印的备份回滚即可

> **与 `ais-pg-upgrade` 的后续版本冲突**：本包按上述 `ais-pg-upgrade` release 的文件哈希编写。如果先升级了 `ais-pg-upgrade`，`check` 会因文件内容不同而拒绝。正确顺序是：先 `rollback` 本包 → 升级 `ais-pg-upgrade` → 等待/制作支持新基线的代理池包 → 再 `apply`。

## 已包含的前端构建产物

`src/aistudio_api/static/` 中已包含与本升级匹配的前端构建产物（含哈希文件名、`index.html` 与 `.vite/manifest.json`），安装后无需 Node 环境即可使用。

如果要自行修改前端：`cd web && bun install && bun run build`（产物输出到 `src/aistudio_api/static/`）。注意自行重建后本包清单会与目录不一致，后续 `apply`/`rollback` 前需确认。

## 维护与测试

安装器行为（真实文件写入、重复应用、冲突拒绝、失败自动恢复、回滚校验、路径逃逸/符号链接防护、CRLF 兼容）由仓库内测试覆盖：

```bash
cd ais-proxy-pool
<python> -m pytest tests -q
```

`payload/` 是相对基线的完整升级文件，`patch-manifest.json` 记录基线、前后哈希与删除项，可用 `check` 复核。

## 来源与许可

- 原项目：[DeconstructedCube/aistudio-api](https://github.com/DeconstructedCube/aistudio-api)（MIT）
- 前置补丁：[Mooece/ais-pg-upgrade](https://github.com/Mooece/ais-pg-upgrade)
- 本仓库仅包含代理池升级的差异文件与安装器，保留原项目与前置补丁的版权与许可声明，详见 [UPSTREAM.md](./UPSTREAM.md) 与 [LICENSE](./LICENSE)。