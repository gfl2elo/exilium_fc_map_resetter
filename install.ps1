# Windows setup. Run from PowerShell; the game does not need to be open.
[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$TesseractPath
)

$ErrorActionPreference = 'Stop'
$setupRoot = $PSScriptRoot
$venvPython = Join-Path $setupRoot '.venv\Scripts\python.exe'
$settingsPath = Join-Path $setupRoot 'settings.json'

function Refresh-SetupPath {
    $env:Path = $env:Path + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Install-PackageWithWinget([string]$PackageId) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw 'WinGet is missing. Install/update App Installer from Microsoft Store, open a new terminal, then rerun install.ps1. See README.md.'
    }
    Write-Host "Installing $PackageId... Windows may request administrator approval."
    & winget.exe install --id $PackageId --exact --source winget --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "WinGet could not install $PackageId (exit $LASTEXITCODE). Resolve the error above and rerun setup."
    }
    Refresh-SetupPath
}

function Find-Python {
    $candidates = @($PythonPath, $venvPython)
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*\WindowsApps\*') {
        $candidates += $command.Source
    }
    foreach ($base in @("$env:LOCALAPPDATA\Programs\Python", $env:ProgramFiles)) {
        if (Test-Path -LiteralPath $base) {
            $candidates += Get-ChildItem -LiteralPath $base -Directory -Filter 'Python3*' | ForEach-Object { Join-Path $_.FullName 'python.exe' }
        }
    }
    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        $found = & $candidate -c "import sys, struct; sys.exit(1) if not ((3,11) <= sys.version_info[:2] <= (3,14) and struct.calcsize('P') == 8) else print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) { return [string]($found | Select-Object -Last 1) }
    }
    return $null
}

function Find-Tesseract {
    $candidates = @($TesseractPath, $script:settings.tesseract)
    $command = Get-Command tesseract.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $candidates += @("$env:ProgramFiles\Tesseract-OCR\tesseract.exe", "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tesseract.exe")
    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            & $candidate --version *> $null
            if ($LASTEXITCODE -eq 0) { return (Resolve-Path -LiteralPath $candidate).Path }
        }
    }
    return $null
}

try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'This installer requires 64-bit Windows.' }
    foreach ($file in @('reset.py', 'desktop.py', 'vision.py', 'requirements.txt', 'settings.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $setupRoot $file) -PathType Leaf)) {
            throw "Missing $file. Extract/copy the entire exilium-reset folder before running setup."
        }
    }
    $script:settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    foreach ($specified in @($PythonPath, $TesseractPath)) {
        if ($specified -and -not (Test-Path -LiteralPath $specified -PathType Leaf)) {
            throw "Executable does not exist: $specified"
        }
    }
    $pythonExe = Find-Python
    if (-not $pythonExe) {
        Install-PackageWithWinget 'Python.Python.3.13'
        $pythonExe = Find-Python
    }
    if (-not $pythonExe) { throw 'Python was not detected. Rerun with -PythonPath pointing to a 64-bit Python 3.11-3.14 python.exe.' }
    Write-Host "Using Python: $pythonExe"

    $ocrExe = Find-Tesseract
    if (-not $ocrExe) {
        Install-PackageWithWinget 'UB-Mannheim.TesseractOCR'
        $ocrExe = Find-Tesseract
    }
    if (-not $ocrExe) { throw 'Tesseract was not detected. Rerun with -TesseractPath pointing to tesseract.exe.' }
    Write-Host "Using Tesseract: $ocrExe"

    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        & $pythonExe -m venv (Join-Path $setupRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python environment.' }
    }
    & $venvPython -m pip install --disable-pip-version-check --no-cache-dir -r (Join-Path $setupRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the error above and rerun setup.' }

    # Check imports and English OCR data without opening or controlling the game.
    & $venvPython -c "import sys, cv2, numpy, PIL, pytesseract; pytesseract.pytesseract.tesseract_cmd=sys.argv[1]; langs=pytesseract.get_languages(config=''); sys.exit('Missing English OCR data (eng). Modify the Tesseract installation to add English.') if 'eng' not in langs else print('Dependencies and English OCR data verified.')" $ocrExe
    if ($LASTEXITCODE -ne 0) { throw 'Dependency/OCR verification failed.' }

    $script:settings.tesseract = $ocrExe
    $json = $script:settings | ConvertTo-Json -Depth 20
    # Python reads UTF-8 without a BOM. Replace only after the new JSON is written.
    $temporarySettings = Join-Path $setupRoot 'settings.setup.tmp'
    [IO.File]::WriteAllText($temporarySettings, $json, (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporarySettings -Destination $settingsPath -Force
    Write-Host ''
    Write-Host 'Setup complete. From this folder, run:'
    Write-Host '  .\.venv\Scripts\python.exe .\reset.py'
    Write-Host 'The game has not been started or controlled.'
} catch {
    Write-Host "Setup stopped: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
