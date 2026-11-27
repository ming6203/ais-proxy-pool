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
| 原项目 | [DeconstructedCube/aistudio-api](https://github.com/DeconstructedCube/aistudio-api) | 提交 `c770aaf3c76a10dbcd6584d033bb76ffa80ccd27` |
| 前置补丁 | [Mooece/ais-pg-upgrade](https://github.com/Mooece/ais-pg-upgrade) | release `20261126-c770-compat`（`d486455`），已 `apply` |
| 本升级包 | 本仓库 | 见 `patch-manifest.json` 的 `release_id` |

> **版本对应**：`v1.1.0` 对应上表（`c770aaf` + `20261126-c770-compat`）；旧的 `v1.0.0` 对应 `a28a6c5` + `20261123-full-reply-tools-8c371879`，仍停留在旧基线的安装请检出 `v1.0.0` tag。详见 [CHANGELOG.md](./CHANGELOG.md)。

清单对每个被修改文件都记录了该基线的 SHA-256。若目标文件与基线不一致（例如先升级了 `ais-pg-upgrade`、手工改过代码或重新构建过前端），`check`/`apply` 会拒绝并指出冲突文件。

## 安装

### 0. 准备

- 原项目已按官方说明安装完成：存在 `.venv`（Python ≥ 3.11）与已编译的 `waa-signer/bin/waa-signer[.exe]`
- 已应用与本包基线一致的 `ais-pg-upgrade`（见上表）并成功启动过一次
- 本升级包与项目放在不同目录，例如 `D:\01Project\aistudio-api` 与 `D:\01Project\ais-proxy-pool`

> 应用前先停止服务并暂停自动重启。代码改动不会热加载，必须重启一个新的服务实例。

### 1. 拉取本仓库

```bash
git clone https://github.com/ming6203/ais-proxy-pool.git ais-proxy-pool
# 国内网络无法直连 HTTPS 时可用 SSH（或先为 git 配置代理）
# git clone git@github.com:ming6203/ais-proxy-pool.git ais-proxy-pool
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

## 升级

### 先判断属于哪种升级

| 情况 | 判断方法 | 走哪一节 |
|---|---|---|
| 同基线升级 | 原项目提交、`ais-pg-upgrade` release 都与上表**一致**，只是本包出了新版本 | [A. 同基线升级](#a-同基线升级) |
| 跨基线升级 | 原项目提交或 `ais-pg-upgrade` release 与上表**不同**（例如从 `v1.0.0` 升到 `v1.1.0`） | [B. 跨基线升级](#b-跨基线升级) |

`check` 若报 `Apply the prerequisite patch first` 或 `Unknown target changes: …`，说明基线不匹配，不要强行继续，按对应流程处理。

> **升级前统一要求**：停止服务；备份 `data/`、`config.yaml`、`.env`（补丁只改代码文件，但多一层保险）；记录当前版本 `patch-manifest.json` 里的 `release_id` 和本次 `apply` 打印的备份目录。
>
> **不要**执行 `git clean -fdx` 或删除 `data/`，那会清掉代理池、账号和统计。

### A. 同基线升级

适用于原项目与前置补丁都没变、只是本包发布新版本（例如 `v1.1.x` → `v1.1.y`）。

**通用步骤**：停服 → `git pull --ff-only` → `check` → `apply` → 按需重编签名器 → 启动 → 验证。

是否重编签名器看新版本是否改了 `waa-signer/`：`git -C "$addon" diff --stat <旧tag>..<新tag> -- payload/waa-signer` 有输出就必须重编。

#### Windows（PowerShell）

```powershell
$project = 'D:\01Project\aistudio-api'
$addon   = 'D:\01Project\ais-proxy-pool'

# 1) 停服：在服务窗口按 Ctrl+C；后台运行时按端口结束
Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess }

# 2) 更新补丁仓库
git -C $addon pull --ff-only

# 3) 检查并应用
& "$project\.venv\Scripts\python.exe" -B "$addon\upgrade.py" check --project $project
& "$project\.venv\Scripts\python.exe" -B "$addon\upgrade.py" apply --project $project

# 4) 如新版本改动签名器
powershell -NoProfile -ExecutionPolicy Bypass -File "$project\waa-signer\build.ps1"

# 5) 启动并验证
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','start.bat' -WorkingDirectory $project
Start-Sleep -Seconds 15
(Invoke-WebRequest 'http://127.0.0.1:8080/health' -UseBasicParsing).Content
(Invoke-WebRequest 'http://127.0.0.1:8080/api/proxies' -UseBasicParsing).Content
```

#### Linux

```bash
project=$HOME/aistudio-api
addon=$HOME/ais-proxy-pool

# 1) 停服：在运行 start.sh 的窗口按 Ctrl+C
# 若为 systemd 服务，见下方「VPS / systemd」

# 2) 更新补丁仓库
git -C "$addon" pull --ff-only

# 3) 检查并应用
"$project/.venv/bin/python" -B "$addon/upgrade.py" check --project "$project"
"$project/.venv/bin/python" -B "$addon/upgrade.py" apply --project "$project"

# 4) 如新版本改动签名器
bash "$project/waa-signer/build.sh"

# 5) 启动并验证
cd "$project" && bash start.sh
# 另开终端
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/api/proxies
```

#### macOS

```bash
project=$HOME/aistudio-api
addon=$HOME/ais-proxy-pool

# 1) 停服：在 start.sh 窗口按 Ctrl+C

# 2) 更新并应用
git -C "$addon" pull --ff-only
"$project/.venv/bin/python" -B "$addon/upgrade.py" check --project "$project"
"$project/.venv/bin/python" -B "$addon/upgrade.py" apply --project "$project"

# 3) 如新版本改动签名器
bash "$project/waa-signer/build.sh"

# 4) 启动并验证
cd "$project" && bash start.sh
# 另开终端
curl -fsS http://127.0.0.1:8080/health
```

#### Termux (Android)

```bash
project=$HOME/aistudio-api
addon=$HOME/ais-proxy-pool

# 1) 在原服务窗口按 Ctrl+C，确认出现 Application shutdown complete

# 2) 更新并应用
git -C "$addon" pull --ff-only
"$project/.venv/bin/python" -B "$addon/upgrade.py" check --project "$project"
"$project/.venv/bin/python" -B "$addon/upgrade.py" apply --project "$project"

# 3) 如新版本改动签名器（Termux 首次编译较慢）
bash "$project/waa-signer/build.sh"

# 4) 启动
cd "$project" && bash start.sh
```

> Termux 没有 systemd：不要用 `systemctl`；需保持 Termux 会话存活，下拉通知栏执行 `Acquire Wakelock`，并在系统设置里关闭 Termux 电池优化。

### B. 跨基线升级

适用于从 `v1.0.0` 升到 `v1.1.0`：基线变了（`a28a6c5` → `c770aaf`，前置补丁 `20261123` → `20261126`），**不能直接 `apply` v1.1.0**，必须按下面的顺序把补丁逐层退回、再逐层升上去：

```
停服
  → 回滚代理池 v1.0.0
  → 回滚旧版 ais-pg-upgrade（20261123-full-reply-tools-8c371879）
  → 原项目代码升级到 c770aaf（重新同步依赖 + 编译签名器）
  → 应用新版 ais-pg-upgrade（20261126-c770-compat）
  → 应用代理池 v1.1.0
  → 重编签名器
  → 启动并验证
```

> 顺序不能反：补丁按文件哈希校验，先装新补丁或先装 v1.1.0 都会被拒绝。回滚只还原被补丁改过的代码，`data/`、`config.yaml`、`.env`、`.venv` 不受影响。
>
> **升级前检查**：`git -C $project status --porcelain` 应为空；若 `config.yaml` 有本地修改，先把它复制到项目外，升级完成后再按需合并（新版本已无 `network` 段）。

#### Windows（PowerShell）

```powershell
$project   = 'D:\01Project\aistudio-api'
$addon     = 'D:\01Project\ais-proxy-pool'          # 当前 v1.0.0 的补丁目录
$addonOld  = 'D:\01Project\ais-pg-upgrade'          # 旧版前置补丁目录
$addonNew  = 'D:\01Project\ais-pg-upgrade-c770'     # 新版前置补丁目录
$py        = "$project\.venv\Scripts\python.exe"

# 0) 停服（服务窗口 Ctrl+C；或以端口方式确认没有监听）
Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue

# 1) 回滚代理池 v1.0.0（备份目录取自当初 apply 的输出，或从升级器默认备份目录里找）
& $py -B "$addon\upgrade.py" rollback --backup 'D:\01Project\ais-proxy-pool-backups\<v1.0.0 备份>'

# 2) 回滚旧版前置补丁
& $py -B "$addonOld\upgrade.py" rollback --backup 'D:\01Project\ais-pg-upgrade-backups\<旧补丁备份>'

# 3) 原项目代码升级到 c770aaf（git 安装方式）
git -C $project fetch origin
git -C $project checkout c770aaf3c76a10dbcd6584d033bb76ffa80ccd27
cd $project; .\install.bat        # 重新同步依赖并编译签名器

# 4) 应用新版前置补丁（20261126-c770-compat）
powershell -NoProfile -ExecutionPolicy Bypass -File "$addonNew\Upgrade-Windows.ps1" -ProjectPath $project -Port 8080 -NoStart

# 5) 应用代理池 v1.1.0（先把本仓库更新到 v1.1.0）
git -C $addon fetch --tags
git -C $addon checkout v1.1.0
& $py -B "$addon\upgrade.py" check --project $project
& $py -B "$addon\upgrade.py" apply --project $project

# 6) 重编签名器（本包改动 Go 源码）
powershell -NoProfile -ExecutionPolicy Bypass -File "$project\waa-signer\build.ps1"

# 7) 启动并验证
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','start.bat' -WorkingDirectory $project
Start-Sleep -Seconds 15
(Invoke-WebRequest 'http://127.0.0.1:8080/health' -UseBasicParsing).Content
(Invoke-WebRequest 'http://127.0.0.1:8080/api/proxies' -UseBasicParsing).Content
```

> **ZIP 安装（非 git）**：跳过第 3 步的 git 命令，下载原项目 `c770aaf` 的源码包，解压覆盖到 `$project`（覆盖代码即可），保留 `data/`、`config.yaml`、`.env`、`.venv`、`waa-signer/.deps`、`waa-signer/bin`，然后执行 `.\install.bat`。

#### Linux

```bash
project=$HOME/aistudio-api
addon=$HOME/ais-proxy-pool                  # v1.0.0 补丁目录
addonOld=$HOME/ais-pg-upgrade               # 旧版前置补丁
addonNew=$HOME/ais-pg-upgrade-c770          # 新版前置补丁
py="$project/.venv/bin/python"

# 0) 停服：在 start.sh 窗口按 Ctrl+C；systemd 见下方

# 1) 回滚代理池 v1.0.0
"$py" -B "$addon/upgrade.py" rollback --backup "$HOME/ais-proxy-pool-backups/<v1.0.0 备份>"

# 2) 回滚旧版前置补丁
"$py" -B "$addonOld/upgrade.py" rollback --backup "$HOME/ais-pg-upgrade-backups/<旧补丁备份>"

# 3) 原项目升级到 c770aaf
git -C "$project" fetch origin
git -C "$project" checkout c770aaf3c76a10dbcd6584d033bb76ffa80ccd27
cd "$project" && bash install.sh

# 4) 应用新版前置补丁
"$py" -B "$addonNew/upgrade.py" check --project "$project"
"$py" -B "$addonNew/upgrade.py" apply --project "$project"

# 5) 更新并应用代理池 v1.1.0
git -C "$addon" fetch --tags
git -C "$addon" checkout v1.1.0
"$py" -B "$addon/upgrade.py" check --project "$project"
"$py" -B "$addon/upgrade.py" apply --project "$project"

# 6) 重编签名器
bash "$project/waa-signer/build.sh"

# 7) 启动并验证
cd "$project" && bash start.sh
# 另开终端
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/api/proxies
```

#### macOS

与 Linux 完全一致（`install.sh`、`start.sh`、`waa-signer/build.sh`、`.venv/bin/python`），把上面的 `$HOME` 路径换成实际目录即可。

#### Termux (Android)

```bash
project=$HOME/aistudio-api
addon=$HOME/ais-proxy-pool
addonOld=$HOME/ais-pg-upgrade
addonNew=$HOME/ais-pg-upgrade-c770
py="$project/.venv/bin/python"

# 1) 在 start.sh 窗口按 Ctrl+C，等待 Application shutdown complete

# 2) 逐层回滚（备份目录取自各自 apply 输出）
"$py" -B "$addon/upgrade.py" rollback --backup "$HOME/ais-proxy-pool-backups/<v1.0.0 备份>"
"$py" -B "$addonOld/upgrade.py" rollback --backup "$HOME/ais-pg-upgrade-backups/<旧补丁备份>"

# 3) 原项目升级到 c770aaf（Termux 下编译较慢）
git -C "$project" fetch origin
git -C "$project" checkout c770aaf3c76a10dbcd6584d033bb76ffa80ccd27
cd "$project" && bash install.sh

# 4) 新版前置补丁 → 5) 代理池 v1.1.0
"$py" -B "$addonNew/upgrade.py" apply --project "$project"
git -C "$addon" fetch --tags && git -C "$addon" checkout v1.1.0
"$py" -B "$addon/upgrade.py" apply --project "$project"

# 6) 重编签名器并启动
bash "$project/waa-signer/build.sh"
cd "$project" && bash start.sh
```

#### VPS / systemd（Linux）

```bash
project=/opt/aistudio-api
addon=/opt/ais-proxy-pool
addonOld=/opt/ais-pg-upgrade
addonNew=/opt/ais-pg-upgrade-c770

sudo systemctl stop aistudio-api
sudo -u aistudio "$project/.venv/bin/python" -B "$addon/upgrade.py" rollback --backup /opt/ais-proxy-pool-backups/<备份>
sudo -u aistudio "$project/.venv/bin/python" -B "$addonOld/upgrade.py" rollback --backup /opt/ais-pg-upgrade-backups/<备份>
sudo -u aistudio git -C "$project" fetch origin
sudo -u aistudio git -C "$project" checkout c770aaf3c76a10dbcd6584d033bb76ffa80ccd27
sudo -u aistudio bash "$project/install.sh"
sudo -u aistudio "$project/.venv/bin/python" -B "$addonNew/upgrade.py" apply --project "$project"
sudo -u aistudio git -C "$addon" fetch --tags
sudo -u aistudio git -C "$addon" checkout v1.1.0
sudo -u aistudio "$project/.venv/bin/python" -B "$addon/upgrade.py" apply --project "$project"
sudo -u aistudio bash "$project/waa-signer/build.sh"
sudo systemctl start aistudio-api
curl -fsS --max-time 5 http://127.0.0.1:8080/health
```

> 备份目录要放在项目外且服务账号可写；`install.sh` 与 `build.sh` 需要当前用户可写项目目录。
>
> 升级完成后建议执行 `git -C "$addon" checkout main` 回到主分支，便于后续同基线更新；此时 `main` 与 `v1.1.0` 内容一致。

#### 升级失败怎么退回 v1.0.0

```text
停服
  → 回滚代理池 v1.1.0
  → 回滚新版前置补丁
  → 原项目代码退回 a28a6c5（git checkout a28a6c5… 或覆盖旧源码包）
  → 重新 install（同步依赖 + 编译签名器）
  → 应用旧版前置补丁（20261123-full-reply-tools-8c371879）
  → 把补丁仓库切回 v1.0.0 并 apply
  → 重编签名器，启动
```

Windows 对应命令：

```powershell
& $py -B "$addon\upgrade.py" rollback --backup '<v1.1.0 备份>'
& $py -B "$addonNew\upgrade.py" rollback --backup '<新版前置补丁备份>'
git -C $project checkout a28a6c5b0790c4efa4495de8393631bf1ae814b1
cd $project; .\install.bat
& $py -B "$addonOld\upgrade.py" apply --project $project
git -C $addon checkout v1.0.0
& $py -B "$addon\upgrade.py" apply --project $project
powershell -NoProfile -ExecutionPolicy Bypass -File "$project\waa-signer\build.ps1"
```

### Docker

本包是**文件级补丁**，需要原项目目录里的 `.venv` 与 `waa-signer` 源码，不能直接打在已构建的镜像上。使用 Docker 时只有两种做法：

1. 改用源码安装（官方 README 的 Windows / Linux / Termux 流程）；
2. 在镜像构建阶段应用：以 `c770aaf` 源码为基础，在 Dockerfile 里先应用 `ais-pg-upgrade 20261126`，再 `COPY` 本包 `payload/` 覆盖、重编签名器，最后构建新镜像。

`ais-pg-upgrade` 自带 Docker 补丁流程；本包不提供 Docker 脚本，也不对容器内文件打补丁。

## 回滚

先停止服务，然后用原项目 Python 执行（Windows / Linux / macOS / Termux 通用，仅解释器路径不同）：

```powershell
# Windows
& "$project\.venv\Scripts\python.exe" -B "$addon\upgrade.py" rollback --backup '上面打印的备份目录'
```

```bash
# Linux / macOS / Termux
"$project/.venv/bin/python" -B "$addon/upgrade.py" rollback --backup '上面打印的备份目录'
```

回滚会校验目标与备份哈希，只还原本次升级涉及的文件；配置、Cookie、账号数据和依赖环境不受影响。回滚后重新编译签名器（`waa-signer` 源码会一起还原），再按原方式启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$project\waa-signer\build.ps1"
```

```bash
bash "$project/waa-signer/build.sh"
```

## 更新与卸载

- 同基线更新：见 [A. 同基线升级](#a-同基线升级)
- 跟随新的原项目 / 前置补丁基线：见 [B. 跨基线升级](#b-跨基线升级)
- 卸载：执行最后一次 `apply` 打印的备份回滚即可，之后按原方式启动

> **与 `ais-pg-upgrade` 的版本冲突**：本包按上表 `ais-pg-upgrade` release 的文件哈希编写，二者必须成套使用。升级顺序永远是「先回滚本包 → 再回滚/升级前置补丁与原项目 → 再应用本包」，不能直接在已改动的树上叠加另一个版本的补丁。

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