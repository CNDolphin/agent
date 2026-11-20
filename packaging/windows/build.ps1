<#
.SYNOPSIS
  构建 Windows 安装包:PyInstaller 冻结桌面客户端,再由 Inno Setup 生成安装向导。

.DESCRIPTION
  仅打包 Python 桌面客户端(client.desktop + client/web/dist),不含 Go 后端。
  在 Windows 上执行;GitHub Actions 与本地共用同一脚本。

  依赖:Python 3.11+(已安装 .[desktop] 与 pyinstaller)、Node.js(npm)、Inno Setup 6。

.EXAMPLE
  ./packaging/windows/build.ps1
  ./packaging/windows/build.ps1 -GatewayBaseUrl https://api.example.com -SkipWebBuild
#>
[CmdletBinding()]
param(
    # 安装包内置 config.yaml 的网关地址,默认与本仓库 config.yaml 一致。
    [string]$GatewayBaseUrl = "http://121.196.163.41/api",
    # 跳过前端构建(CI 已在前面执行 npm run build)。
    [switch]$SkipWebBuild
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
Write-Host "仓库根目录: $Root"

# 1. 版本号取自 pyproject.toml
$pyproject = Get-Content (Join-Path $Root "pyproject.toml") -Raw
if ($pyproject -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
    throw "无法从 pyproject.toml 读取版本号"
}
$AppVersion = $Matches[1]
Write-Host "版本号: $AppVersion"

# 2. 前端产物
$WebDir = Join-Path $Root "client\web"
$DistIndex = Join-Path $WebDir "dist\index.html"
if (-not $SkipWebBuild -or -not (Test-Path $DistIndex)) {
    Write-Host "构建前端..."
    Push-Location $WebDir
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci 失败" }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build 失败" }
    }
    finally {
        Pop-Location
    }
}
if (-not (Test-Path $DistIndex)) {
    throw "前端产物缺失: $DistIndex(请先在 client/web 执行 npm run build)"
}

# 3. 生成分发配置(替换网关地址占位符)
$TemplatePath = Join-Path $Root "packaging\windows\config.windows.yaml"
$GeneratedConfig = Join-Path $Root "build\windows\config.yaml"
New-Item -ItemType Directory -Force -Path (Split-Path $GeneratedConfig) | Out-Null
$ConfigText = (Get-Content $TemplatePath -Raw -Encoding UTF8).Replace("__GATEWAY_BASE_URL__", $GatewayBaseUrl)
# 显式写成无 BOM 的 UTF-8,避免 Windows PowerShell 5.1 的 Set-Content 加上 BOM 影响 yaml 解析。
[System.IO.File]::WriteAllText($GeneratedConfig, $ConfigText, [System.Text.UTF8Encoding]::new($false))
Write-Host "网关地址: $GatewayBaseUrl"

# 4. PyInstaller 冻结
Write-Host "清理旧产物..."
foreach ($dir in @("dist", "build\pyinstaller")) {
    $path = Join-Path $Root $dir
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}
Write-Host "PyInstaller 打包..."
python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $Root "dist") `
    --workpath (Join-Path $Root "build\pyinstaller") `
    (Join-Path $Root "packaging\windows\mhagent.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }

$ExePath = Join-Path $Root "dist\mhagent-desktop\mhagent-desktop.exe"
if (-not (Test-Path $ExePath)) { throw "未找到冻结产物: $ExePath" }

# 5. Inno Setup 编译
$IsccCandidates = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and (Test-Path $_) }
$Iscc = @($IsccCandidates)[0]
if (-not $Iscc) {
    throw "未找到 Inno Setup 编译器 ISCC.exe,请先安装:choco install innosetup --no-progress -y"
}

Write-Host "编译安装包..."
New-Item -ItemType Directory -Force -Path (Join-Path $Root "artifacts") | Out-Null
& $Iscc "/DAppVersion=$AppVersion" (Join-Path $Root "packaging\windows\installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup 编译失败" }

$SetupPath = Join-Path $Root "artifacts\mhagent-setup-$AppVersion.exe"
if (-not (Test-Path $SetupPath)) { throw "未找到安装包: $SetupPath" }

$Hash = (Get-FileHash $SetupPath -Algorithm SHA256).Hash
Write-Host ""
Write-Host "安装包: $SetupPath"
Write-Host "SHA256: $Hash"
