@echo off
REM Simple wrapper for model-factory commands

if "%1"=="" goto help
if "%1"=="run" goto run
if "%1"=="help" goto help

echo Unknown command: %1
goto help

:run
model-factory %*
exit /b %errorlevel%

:help
echo Model Factory Generator
echo.
echo Usage: generator [command] [options]
echo.
echo Commands:
echo   run              Run model-factory with default settings
echo   help             Show this help message
echo.
echo Examples:
echo   generator run
echo   generator run --creature pupplynx
echo   generator run --preset "Hunyuan3D-2 Turbo (faster)"
echo.
echo For full options, use: model-factory --help
exit /b 0
