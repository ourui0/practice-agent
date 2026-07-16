$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
foreach ($Name in @("build", "dist", ".pytest_cache", ".ruff_cache")) {
    $Target = Join-Path $ProjectRoot $Name
    if (Test-Path -LiteralPath $Target) {
        Remove-Item -LiteralPath $Target -Recurse -Force
    }
}
Write-Host "已清理构建和测试缓存。"
