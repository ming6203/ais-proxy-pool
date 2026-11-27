#Requires -Version 5.1
<#
.SYNOPSIS
    应用「aistudio-api 代理池升级包」：检查端口与安装状态、应用补丁、重编签名器并启动服务。
.DESCRIPTION
    只做文件检查、备份与应用，不代装原项目或依赖。必须先停止旧服务。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ProjectPath,
    [int]$Port = 8080,
    [switch]$SkipSigner,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$project = (Resolve-Path -LiteralPath $ProjectPath).Path
$addon = if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) { $PSScriptRoot } else { (Get-Location).Path }
$python = Join-Path $project '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到原项目虚拟环境: $python。请先按原项目说明完成安装。"
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    throw "端口 $Port 仍被占用 (PID $($listener.OwningProcess))。请先停止原服务，等待退出后再运行。"
}

Write-Host "==> 检查安装与补丁基线: $project" -ForegroundColor Cyan
& $python -B (Join-Path $addon 'upgrade.py') check --project $project
if ($LASTEXITCODE -ne 0) { throw '检查未通过，未做任何改动。' }

Write-Host "==> 应用升级（会先备份原文件）" -ForegroundColor Cyan
& $python -B (Join-Path $addon 'upgrade.py') apply --project $project
if ($LASTEXITCODE -ne 0) { throw '应用失败，已按备份自动恢复。' }

if (-not $SkipSigner) {
    Write-Host "==> 重新编译 WAA 签名器（支持 direct 语义）" -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $project 'waa-signer\build.ps1')
    if ($LASTEXITCODE -ne 0) { throw '签名器编译失败，请查看上方输出；服务尚未启动。' }
}

if ($NoStart) {
    Write-Host '==> 已完成文件升级。请按原方式启动服务（start.bat）。' -ForegroundColor Green
    exit 0
}

Write-Host "==> 启动服务: http://localhost:$Port" -ForegroundColor Cyan
Push-Location -LiteralPath $project
try {
    & (Join-Path $project 'start.bat')
} finally {
    Pop-Location
}