<# =============================================================================
   MIRT AI - Telegram Bot Launcher for Windows PowerShell
   =============================================================================

   This script launches the Telegram bot from the repository root with proper
   environment setup and optional cleanup of hanging processes.

   Usage:
   - Run normally: .\scripts\start_telegram_bot.ps1
   - Run in background: .\scripts\start_telegram_bot.ps1 -Background
   - Cleanup only: .\scripts\start_telegram_bot.ps1 -CleanupOnly
#>

param (
    [switch]$Background,
    [switch]$CleanupOnly
)

# Set script execution policy to allow running this script
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# Function to cleanup hanging polling processes
function Cleanup-HangingProcesses {
    Write-Host "🧹 Cleaning up hanging polling processes..."
    try {
        $processes = Get-Process python | Where-Object { $_.CommandLine -match 'telegram_bot' }
        if ($processes) {
            Write-Host "Found $($processes.Count) hanging processes, stopping them..."
            $processes | Stop-Process -Force
            Write-Host "✅ Cleanup completed."
        } else {
            Write-Host "✅ No hanging processes found."
        }
    } catch {
        Write-Warning "⚠️  Error during cleanup: $_"
    }
}

# Function to start the bot
function Start-TelegramBot {
    Write-Host "🚀 Starting Telegram bot..."

    # Set environment variables
    $env:PYTHONPATH = "."
    $env:LOG_LEVEL = "DEBUG"

    # Load .env file if it exists
    if (Test-Path ".env") {
        Write-Host "📄 Loading environment variables from .env file..."
        # Note: PowerShell doesn't natively support .env files, but Python will load it
        # We just need to ensure the working directory is correct
    }

    # Build the command
    $command = "python -m src.bot.telegram_bot"

    if ($Background) {
        Write-Host "🔄 Starting bot in background..."
        Start-Process python -ArgumentList "-m src.bot.telegram_bot" -NoNewWindow
        Write-Host "🎯 Bot started in background. Check process list if needed."
    } else {
        Write-Host "🎯 Starting bot in foreground..."
        Write-Host "💡 Press Ctrl+C to stop the bot"
        Write-Host "============================================================================="
        # Execute the command
        Invoke-Expression $command
    }
}

# Main execution
try {
    # Always cleanup if requested or if running in background
    if ($CleanupOnly -or $Background) {
        Cleanup-HangingProcesses
    }

    if (-not $CleanupOnly) {
        Start-TelegramBot
    } else {
        Write-Host "🎯 Cleanup completed. No bot started."
    }
} catch {
    Write-Error "❌ Failed to start Telegram bot: $_"
    exit 1
}