$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$taskPython = Join-Path (Get-Location) '.venv/Scripts/python.exe'
foreach ($taskModule in @('triage.data', 'triage.train', 'triage.verify_skill', 'triage.evaluate')) {
    & $taskPython -m $taskModule
    if ($LASTEXITCODE -ne 0) { throw "失败步骤：$taskModule" }
}
& $taskPython -m pytest -q
if ($LASTEXITCODE -ne 0) { throw '验收测试未通过。' }
