param(
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ReleasePython = Join-Path $ProjectRoot ".release-venv\Scripts\python.exe"
$DevelopmentPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $ReleasePython) {
    $ReleasePython
} elseif (Test-Path -LiteralPath $DevelopmentPython) {
    $DevelopmentPython
} else {
    throw "No Python environment was found. Create .release-venv and install .[dev,release]."
}

$PyProject = Get-Content (Join-Path $ProjectRoot "pyproject.toml") -Raw -Encoding utf8
$VersionMatch = [regex]::Match($PyProject, '(?m)^version\s*=\s*"([^"]+)"')
if (-not $VersionMatch.Success) {
    throw "Unable to read the version from pyproject.toml."
}
$Version = $VersionMatch.Groups[1].Value

Push-Location $ProjectRoot
try {
    if (-not $SkipTests) {
        & $Python -m ruff check src tests
        if ($LASTEXITCODE -ne 0) { throw "Ruff checks failed." }

        $env:QT_QPA_PLATFORM = "offscreen"
        & $Python -m pytest
        if ($LASTEXITCODE -ne 0) { throw "Automated tests failed." }
    }

    & $Python -m PyInstaller --noconfirm --clean "packaging\EduExamAgent.spec"
    if ($LASTEXITCODE -ne 0) { throw "Application build failed." }

    $Executable = Join-Path $ProjectRoot "dist\EduExamAgent\EduExamAgent.exe"
    if (-not (Test-Path -LiteralPath $Executable)) {
        throw "EduExamAgent.exe was not found after the build."
    }

    if ($SkipInstaller) {
        Write-Host "Application created: $Executable"
        return
    }

    $CompilerCandidates = @(
        (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path $ProjectRoot "tmp\InnoSetup6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

    $Compiler = $CompilerCandidates | Select-Object -First 1
    if (-not $Compiler) {
        throw "Inno Setup 6 was not found. Install it or use -SkipInstaller."
    }

    & $Compiler "/DAppVersion=$Version" "packaging\EduExamAgent.iss"
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed." }

    $Installer = Join-Path $ProjectRoot "release\EduExamAgent-Setup-$Version.exe"
    if (-not (Test-Path -LiteralPath $Installer)) {
        throw "The installer was not found after the build."
    }
    Write-Host "Installer created: $Installer"
}
finally {
    Pop-Location
}
