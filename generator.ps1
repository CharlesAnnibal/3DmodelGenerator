param(
    [string]$Command = "help",
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Args
)

function Show-Help {
    @"
Model Factory Generator

Usage: .\generator [command] [options]

Commands:
  run              Run model-factory with default settings
  help             Show this help message

Examples:
  .\generator run
  .\generator run --creature worcomb
  .\generator run --preset "Hunyuan3D-2 Turbo (faster)"

For full options, use: model-factory --help
"@
}

switch ($Command) {
    "run" {
        & python -m model_generator_cli @Args
        exit $LASTEXITCODE
    }
    "help" {
        Show-Help
        exit 0
    }
    default {
        Write-Host "Unknown command: $Command" -ForegroundColor Red
        Show-Help
        exit 1
    }
}
