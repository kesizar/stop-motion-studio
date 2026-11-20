param([switch]$SetupOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtime = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$check = 'import sys, tkinter; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) and sys.maxsize > 2**32 else 1)'
if (-not (Test-Path -LiteralPath $runtime)) {
    $found = $false
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $available = (& py -0p | Out-String)
        foreach ($version in @('-3.11','-3.12','-3.10')) {
            if (-not $available.Contains($version.Substring(1))) { continue }
            & py $version -c $check
            if ($LASTEXITCODE -eq 0) {
                & py $version -m venv .venv
                if ($LASTEXITCODE -ne 0) { throw 'Unable to create the project environment.' }
                $found = $true
                break
            }
        }
    }
    if (-not $found) {
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCmd -and $pythonCmd.Source -notlike '*\Microsoft\WindowsApps\python.exe') {
            & $pythonCmd.Source -c $check
            if ($LASTEXITCODE -eq 0) {
                & $pythonCmd.Source -m venv .venv
                $found = ($LASTEXITCODE -eq 0)
            }
        }
    }
    if (-not $found) { throw 'Install 64-bit Python 3.11 with Tcl/Tk and the Python launcher, then open this launcher again.' }
}
$requirements = Join-Path $PSScriptRoot 'requirements.txt'
$marker = Join-Path $PSScriptRoot '.venv\installed-requirements.txt'
$digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirements).Hash
if ((-not (Test-Path -LiteralPath $marker)) -or (Get-Content -LiteralPath $marker -Raw).Trim() -ne $digest) {
    Write-Host 'Installing project dependencies. First launch requires internet access.'
    & $runtime -m pip install --disable-pip-version-check -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your internet connection, then retry.' }
    & $runtime -c 'import cv2, numpy as np, tkinter, PIL; from sources import HandDetector; h=HandDetector(); assert not h.sees_hand(np.zeros((160,160,3),np.uint8),0.0); h.detector.close()'
    if ($LASTEXITCODE -ne 0) { throw 'Hand tracking initialization failed. See errors above.' }
    Set-Content -LiteralPath $marker -Value $digest -Encoding ASCII
}
if (-not $SetupOnly) {
    & $runtime (Join-Path $PSScriptRoot 'app.py')
    exit $LASTEXITCODE
}
