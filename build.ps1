# KeyPulse build script (Windows)
#
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
#
# -NoPause    skip the "press enter" at the end (use this in CI)
# -OutDir     where the release zip is written; default is .\release
# -InstallTo  also drop the fresh exe into this folder -- the one you actually
#             run KeyPulse from, which is where its stats.json lives. Nothing
#             is copied anywhere unless you ask for it, so a clone of this
#             repository builds without knowing about anybody's folders.
param(
    [switch]$NoPause,
    [string]$OutDir,
    [string]$InstallTo
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

# The version is written here once. version_info.txt must agree with it, or
# step 1 stops the build.
$Version = "1.0.0"

# Everything the build produces stays inside the repository unless the caller
# says otherwise, so a clone builds without knowing anything about the machine
# it was cloned onto. release/ is in .gitignore.
if (-not $OutDir) { $OutDir = Join-Path $PSScriptRoot "release" }
$StageRoot = Join-Path $env:TEMP "KeyPulse_build_$Version"
$WinStage  = Join-Path $StageRoot "KeyPulse_v$Version"
$WinZip    = Join-Path $OutDir "KeyPulse_v${Version}_Windows_x64.zip"

function New-Zip($SourceDir, $ZipPath) {
    # .NET rather than Compress-Archive: Windows PowerShell 5.1's version
    # writes backslashes as the path separator, which non-Windows unzip tools
    # read as part of the file name.
    Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $SourceDir, $ZipPath, [System.IO.Compression.CompressionLevel]::Optimal, $true)
}

Write-Host "[1/6] Checking the environment..." -ForegroundColor Cyan
$Py = $null
foreach ($c in @("python", "py")) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { $Py = $c; break }
}
if (-not $Py) { throw "Python not found. Install Python 3.11+ and tick 'Add to PATH'." }
& $Py -c "import PyInstaller, PySide6" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Missing dependencies, installing requirements.txt ..." -ForegroundColor Yellow
    & $Py -m pip install -r requirements.txt
}
if ((Get-Content "version_info.txt" -Raw) -notmatch [regex]::Escape($Version)) {
    throw "version_info.txt does not say $Version. Sync the two before building."
}

Write-Host "[2/6] Running the tests..." -ForegroundColor Cyan
$env:PYTHONPATH = $PSScriptRoot
foreach ($t in @("tests\test_core.py", "tests\test_lighting.py", "tests\test_gallery.py",
                 "tests\test_i18n.py")) {
    & $Py $t
    if ($LASTEXITCODE -ne 0) { throw "Tests failed: $t -- build aborted." }
}

Write-Host "[3/6] Closing any running KeyPulse..." -ForegroundColor Cyan
Get-Process KeyPulse -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 800

Write-Host "[4/6] Building the exe (1-3 minutes)..." -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $Py -m PyInstaller --noconfirm --clean KeyPulseOnefile.spec
$Exe = Join-Path $PSScriptRoot "dist\KeyPulse.exe"
if (-not (Test-Path $Exe)) { throw "Build failed: dist\KeyPulse.exe was not produced." }

Write-Host "[5/6] Staging the Windows zip..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
Remove-Item -Recurse -Force $StageRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $WinStage -Force | Out-Null
Copy-Item $Exe                         $WinStage -Force
Copy-Item ".\docs\USER_GUIDE.zh-CN.txt" $WinStage -Force
Copy-Item ".\THIRD_PARTY_NOTICES.txt"  $WinStage -Force
Copy-Item ".\LICENSE"                  $WinStage -Force
New-Zip $WinStage $WinZip
Remove-Item -Recurse -Force $StageRoot

# Before the cleanup below deletes dist\, since that is where the exe still is.
$Installed = $null
if ($InstallTo) {
    if (-not (Test-Path -LiteralPath $InstallTo)) {
        throw "-InstallTo folder does not exist: $InstallTo"
    }
    $Installed = Join-Path $InstallTo "KeyPulse.exe"
    Copy-Item $Exe $Installed -Force
    Write-Host "  installed to $Installed"
}

Write-Host "[6/6] Cleaning up..." -ForegroundColor Cyan
# Old version zips in the output folder are not this build's and only confuse
# whoever goes looking for the one that was just made.
Get-ChildItem -LiteralPath $OutDir -Filter "KeyPulse_v*.zip" |
    Where-Object { $_.Name -notlike "*_v${Version}_*" } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force; Write-Host "  removed old $($_.Name)" }
Remove-Item -Recurse -Force build, dist, __pycache__, "tests\__pycache__" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done -- version $Version." -ForegroundColor Green
Write-Host "  $WinZip"
if ($Installed) { Write-Host "  $Installed" }
Write-Host ""
Write-Host "GitHub attaches the source archives to a release by itself;" -ForegroundColor DarkGray
Write-Host "upload this zip as the binary asset." -ForegroundColor DarkGray
Write-Host ""
Write-Host "Note: the build stopped any running KeyPulse. Reopen it to resume counting." -ForegroundColor Yellow
if (-not $NoPause) { Read-Host "Press enter to close" }
