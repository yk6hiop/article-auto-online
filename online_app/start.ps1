param(
    [int]$Port = 8010,
    [string]$HostName = "127.0.0.1"
)

Set-Location (Split-Path -Parent $PSScriptRoot)
python -m uvicorn online_app.app:app --host $HostName --port $Port
