<#
Local launcher for Mirt-AI with ngrok.

Usage:
  .\start.ps1
  .\start.ps1 -Reload
  .\start.ps1 -NgrokAuthToken "<token>" -Region "eu"
  .\start.ps1 -Detach
#>

[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$Host = "0.0.0.0",
    [string]$Region = "us",
    [string]$NgrokAuthToken = "",
    [string]$NgrokDomain = "",
    [string]$PythonExe = "",
    [string]$NgrokExe = "ngrok",
    [string]$EnvFile = ".env",
    [switch]$Reload,
    [switch]$Detach
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-CommandPath {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$ExplicitPath = ""
    )

    if ($ExplicitPath) {
        if (Test-Path $ExplicitPath) {
            return (Resolve-Path $ExplicitPath).Path
        }
        throw "Provided path for '$Name' does not exist: $ExplicitPath"
    }

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        return $cmd.Source
    }

    throw "'$Name' was not found in PATH."
}

function Resolve-PythonPath {
    param([string]$Explicit)

    if ($Explicit) {
        return Resolve-CommandPath -Name "python" -ExplicitPath $Explicit
    }
    if (Test-Path ".\.venv\Scripts\python.exe") {
        return (Resolve-Path ".\.venv\Scripts\python.exe").Path
    }
    if (Test-Path ".\venv\Scripts\python.exe") {
        return (Resolve-Path ".\venv\Scripts\python.exe").Path
    }
    return Resolve-CommandPath -Name "python"
}

function Import-DotEnv {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed -split "=", 2
        if ($parts.Count -ne 2) {
            continue
        }
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim("'").Trim('"')
        $existing = Get-Item -Path ("Env:{0}" -f $key) -ErrorAction SilentlyContinue
        if ($key -and -not [string]::IsNullOrWhiteSpace($value) -and $null -eq $existing) {
            Set-Item -Path ("Env:{0}" -f $key) -Value $value
        }
    }
}

function Wait-ForTcpPort {
    param(
        [string]$HostName,
        [int]$TargetPort,
        [int]$TimeoutSec = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $client = [System.Net.Sockets.TcpClient]::new()
        try {
            $iar = $client.BeginConnect($HostName, $TargetPort, $null, $null)
            if ($iar.AsyncWaitHandle.WaitOne(750) -and $client.Connected) {
                $client.EndConnect($iar)
                return $true
            }
        } catch {
            # Keep polling until timeout.
        } finally {
            $client.Dispose()
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Wait-ForNgrokUrl {
    param([int]$TimeoutSec = 30)

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2
            if ($tunnels.tunnels -and $tunnels.tunnels.Count -gt 0) {
                return $tunnels.tunnels[0].public_url
            }
        } catch {
            # Keep polling until ngrok API is ready.
        }
        Start-Sleep -Milliseconds 300
    }
    return $null
}

function Stop-ProcessSafe {
    param([System.Diagnostics.Process]$Process)
    if ($null -eq $Process) {
        return
    }
    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
}

$serverProc = $null
$ngrokProc = $null
$detached = $Detach.IsPresent

try {
    $repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    Set-Location $repoRoot
    Import-DotEnv -Path $EnvFile

    $python = Resolve-PythonPath -Explicit $PythonExe
    $ngrok = Resolve-CommandPath -Name "ngrok" -ExplicitPath $NgrokExe
    $env:PYTHONPATH = "."

    if (-not $NgrokAuthToken) {
        $NgrokAuthToken = $env:NGROK_AUTHTOKEN
    }
    if ($NgrokAuthToken) {
        & $ngrok config add-authtoken $NgrokAuthToken | Out-Null
    }

    $uvicornArgs = @(
        "-m", "uvicorn",
        "src.server.main:app",
        "--host", $Host,
        "--port", "$Port"
    )
    if ($Reload) {
        $uvicornArgs += "--reload"
    }

    $serverProc = Start-Process -FilePath $python -ArgumentList $uvicornArgs -PassThru
    if (-not (Wait-ForTcpPort -HostName "127.0.0.1" -TargetPort $Port -TimeoutSec 30)) {
        throw "Local API did not open on port $Port."
    }

    $ngrokArgs = @("http", "$Port", "--region", $Region)
    if ($NgrokDomain) {
        $ngrokArgs += @("--domain", $NgrokDomain)
    }
    $ngrokProc = Start-Process -FilePath $ngrok -ArgumentList $ngrokArgs -PassThru

    $publicUrl = Wait-ForNgrokUrl -TimeoutSec 30

    Write-Host "Server PID : $($serverProc.Id)"
    Write-Host "ngrok  PID : $($ngrokProc.Id)"
    if ($publicUrl) {
        Write-Host "Public URL : $publicUrl"
        Write-Host "Webhook URL: $publicUrl/webhooks/manychat"
        Write-Host "API URL    : $publicUrl/api/v1/messages"
    } else {
        Write-Host "ngrok dashboard: http://127.0.0.1:4040"
    }

    if ($detached) {
        Write-Host "Detached mode: processes are running in background."
        exit 0
    }

    Write-Host "Press Ctrl+C to stop."
    while ($true) {
        Start-Sleep -Seconds 1
        if ($serverProc.HasExited -or $ngrokProc.HasExited) {
            break
        }
    }
}
catch {
    Write-Error $_
    exit 1
}
finally {
    if (-not $detached) {
        Stop-ProcessSafe -Process $serverProc
        Stop-ProcessSafe -Process $ngrokProc
    }
}
