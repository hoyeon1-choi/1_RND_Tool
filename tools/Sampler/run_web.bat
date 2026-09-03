@echo off
setlocal
cd /d "%~dp0"

set "SAMPLER_HOST=0.0.0.0"
if "%SAMPLER_PORT%"=="" set "SAMPLER_PORT=8765"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 main.py --web --host %SAMPLER_HOST% --port %SAMPLER_PORT%
    goto :end
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python main.py --web --host %SAMPLER_HOST% --port %SAMPLER_PORT%
    goto :end
)

echo Python 3 was not found. Please install Python 3 and run this file again.
pause

:end
endlocal
