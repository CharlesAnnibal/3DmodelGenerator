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
  run              Run the generation pipeline on creature folders
  clean            Remove intermediate/debug artifacts from creature folders
  help             Show this help message

Examples:
  .\generator run
  .\generator run --creature my-creature
  .\generator run --preset "Hunyuan3D-2 Turbo (faster)"
  .\generator clean
  .\generator clean --creature my-creature
  .\generator clean --dry-run

For full options, use: model-factory run --help
"@
}

switch ($Command) {
    "run" {
        $Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $Python)) {
            $Python = "python"
        }
        & $Python -m model_generator_cli run @Args
        exit $LASTEXITCODE
    }
    "clean" {
        $Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $Python)) {
            $Python = "python"
        }
        & $Python -m model_generator_cli clean @Args
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
