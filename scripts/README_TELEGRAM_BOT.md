# Telegram Bot Launcher

This directory contains scripts for launching the Telegram bot.

## Available Scripts

### `start_telegram_bot.ps1`

A PowerShell script for launching the Telegram bot on Windows with proper environment setup.

## Usage

### Basic Usage (Foreground)
```powershell
.\scripts\start_telegram_bot.ps1
```

### Background Mode
```powershell
.\scripts\start_telegram_bot.ps1 -Background
```

### Cleanup Only
```powershell
.\scripts\start_telegram_bot.ps1 -CleanupOnly
```

## Features

- **Automatic Environment Setup**: Sets `PYTHONPATH` and `LOG_LEVEL` environment variables
- **Process Cleanup**: Optionally cleans up hanging Python processes running the telegram bot
- **Background Mode**: Can run the bot in background using `-Background` flag
- **.env Support**: Automatically loads environment variables from `.env` file
- **Error Handling**: Proper error handling and user feedback

## Requirements

- Windows PowerShell 5.1 or later
- Python 3.8+ installed and in PATH
- `.env` file in repository root with required configuration

## Environment Variables

The script sets these environment variables automatically:
- `PYTHONPATH=."` - Ensures Python can find the src module
- `LOG_LEVEL="DEBUG"` - Sets logging level to DEBUG for development

## Notes

- The script uses `python -m src.bot.telegram_bot` to launch the bot
- For production use, consider using the proper deployment methods described in `docs/DEPLOYMENT.md`
- The cleanup feature stops processes that have 'telegram_bot' in their command line