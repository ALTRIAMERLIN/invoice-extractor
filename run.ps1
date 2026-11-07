$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$invoicePython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $invoicePython)) {
    Write-Host 'Create the environment first:'
    Write-Host '  py -3.11 -m venv .venv'
    Write-Host '  .venv/Scripts/python.exe -m pip install -r requirements.txt'
    exit 1
}
& $invoicePython -m streamlit run app.py
exit $LASTEXITCODE
