$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到虚拟环境。请先按 README 创建 .venv 并安装依赖。"
}

Push-Location $ProjectRoot
try {
    & $Python -m edu_exam_agent.app.main
}
finally {
    Pop-Location
}

