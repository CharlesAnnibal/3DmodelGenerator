@echo off
REM Simple wrapper for model-factory commands

if "%1"=="" goto help
if "%1"=="run" goto run
if "%1"=="clean" goto clean
if "%1"=="help" goto help

echo Unknown command: %1
goto help

:run
model-factory run %*
exit /b %errorlevel%

:clean
model-factory clean %*
exit /b %errorlevel%

:help
echo Model Factory Generator
echo.
echo Usage: generator [command] [options]
echo.
echo Commands:
echo   run              Run the generation pipeline on creature folders
echo   clean            Remove intermediate/debug artifacts from creature folders
echo   help             Show this help message
echo.
echo Examples:
echo   generator run
echo   generator run --creature my-creature
echo   generator run --preset "Hunyuan3D-2 Turbo (faster)"
echo   generator clean
echo   generator clean --creature my-creature
echo   generator clean --dry-run
echo.
echo For full options, use: model-factory run --help
exit /b 0
