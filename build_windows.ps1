<#
  Aurelia Finance Lab - reproducible Windows build.

  Run from the project folder in PowerShell:
      powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
  Options:
      -Python "C:\Path\to\python.exe"   use a specific Python 3.12 interpreter
      -SkipTests                         skip the pytest run (not recommended)

  Steps: check Python 3.12 -> create .venv-build -> install the pinned lock file ->
  run the test suite -> PyInstaller one-folder build -> run the built .exe self-test ->
  zip the folder and write SHA-256 checksums and build\BUILD_RESULT.txt.
  The script stops at the first failure and never reports success for a step that did not pass.
#>
param(
    [string]$Python = "",
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host ""; Write-Host "BUILD FAILED: $msg" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- 1. Python 3.12
Step "Locating Python 3.12"
if (-not $Python) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { $Python = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null) }
}
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd.Source }
}
if (-not $Python) { Fail "Python 3.12 not found. Install it from https://www.python.org/downloads/ (64-bit) and re-run." }
$ver = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($ver -ne "3.12") { Fail "Found Python $ver at $Python; this build is pinned and verified for Python 3.12 (64-bit). Pass -Python <path to python 3.12>." }
$bits = & $Python -c "import struct; print(struct.calcsize('P') * 8)"
if ($bits -ne "64") { Fail "A 64-bit Python 3.12 is required (found $bits-bit)." }
Write-Host "Using $Python (Python $ver, $bits-bit)"

# ---------------------------------------------------------------- 2. virtual environment
Step "Creating build environment (.venv-build)"
if (-not (Test-Path ".venv-build\Scripts\python.exe")) {
    & $Python -m venv .venv-build
    if ($LASTEXITCODE -ne 0) { Fail "could not create the virtual environment" }
}
$VPy = Join-Path $PSScriptRoot ".venv-build\Scripts\python.exe"
& $VPy -m pip install --upgrade pip==24.3.1 --quiet
if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed (check your internet connection or proxy)" }

Step "Installing pinned dependencies (requirements-lock.txt)"
& $VPy -m pip install --only-binary=:all: -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { Fail "dependency installation failed" }

# ---------------------------------------------------------------- 3. tests
New-Item -ItemType Directory -Force -Path build | Out-Null
if ($SkipTests) {
    Write-Host "Tests skipped at your request." -ForegroundColor Yellow
    $testResult = "SKIPPED (-SkipTests)"
} else {
    Step "Running the test suite"
    $env:QT_QPA_PLATFORM = "offscreen"
    # Windows PowerShell turns redirected stderr lines (e.g. Qt warnings) into errors; let pytest's exit code decide
    $ErrorActionPreference = "Continue"
    & $VPy -m pytest -q --junitxml=build\test-results.xml 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath build\test-output.txt
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    Remove-Item Env:\QT_QPA_PLATFORM
    if ($code -ne 0) { Fail "tests failed - see build\test-output.txt" }
    $testResult = (Get-Content build\test-output.txt | Select-Object -Last 1)
}

# ---------------------------------------------------------------- 4. PyInstaller
Step "Building the executable with PyInstaller"
if (Test-Path "dist\Aurelia_Finance_Lab") { Remove-Item -Recurse -Force "dist\Aurelia_Finance_Lab" }
& $VPy -m PyInstaller --clean --noconfirm packaging\aurelia.spec
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller failed" }
$Exe = "dist\Aurelia_Finance_Lab\Aurelia_Finance_Lab.exe"
if (-not (Test-Path $Exe)) { Fail "PyInstaller finished but $Exe does not exist" }

# ---------------------------------------------------------------- 5. self-test of the built exe
Step "Running the built executable's self-test"
$tmpData = Join-Path $env:TEMP ("aurelia-build-check-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmpData | Out-Null
$report = Join-Path $PSScriptRoot "build\exe-selftest-report.txt"
$p = Start-Process -FilePath $Exe -ArgumentList @("--selftest", "--quiet", "--report", "`"$report`"", "--data-dir", "`"$tmpData`"") -Wait -PassThru
if ($p.ExitCode -ne 0) { Fail "the built executable's self-test failed (exit $($p.ExitCode)) - see $report" }
if (-not (Select-String -Path $report -Pattern "Overall: PASSED" -Quiet)) { Fail "self-test report does not say PASSED - see $report" }
Remove-Item -Recurse -Force $tmpData -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- 6. package
Step "Packaging"
$version = & $VPy -c "import aurelia; print(aurelia.__version__)"
$zip = "dist\Aurelia_Finance_Lab-$version-win64.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path "dist\Aurelia_Finance_Lab" -DestinationPath $zip
$hExe = (Get-FileHash $Exe -Algorithm SHA256).Hash
$hZip = (Get-FileHash $zip -Algorithm SHA256).Hash
"$hExe  Aurelia_Finance_Lab.exe`n$hZip  $(Split-Path $zip -Leaf)" | Set-Content -Encoding ascii "dist\SHA256SUMS.txt"

$summary = @"
Aurelia Finance Lab $version - Windows build result
Built:        $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Machine:      $([System.Environment]::OSVersion.VersionString), $env:PROCESSOR_ARCHITECTURE
Python:       $(& $VPy --version)
PyInstaller:  $(& $VPy -m PyInstaller --version)
Tests:        $testResult
Exe:          $Exe
Exe self-test: PASSED (report: build\exe-selftest-report.txt)
Package:      $zip
SHA-256 exe:  $hExe
SHA-256 zip:  $hZip
"@
$summary | Set-Content -Encoding utf8 build\BUILD_RESULT.txt
Write-Host ""
Write-Host $summary -ForegroundColor Green
Write-Host "BUILD SUCCEEDED. Start the app with: $Exe" -ForegroundColor Green
