$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$taskPython = Join-Path (Get-Location) '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw '先按 README 创建 .venv 并安装 requirements-lock.txt。'
}
if (-not (Test-Path -LiteralPath 'models/model.joblib')) {
    throw '先运行 python -m triage.data 和 python -m triage.train。'
}
& $taskPython -m triage.web
if ($LASTEXITCODE -ne 0) { throw 'Agent 启动失败，请查看错误信息。' }
