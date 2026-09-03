@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 goto :use_py

where python >nul 2>nul
if not errorlevel 1 goto :use_python

echo Python 3 was not found. Please install Python 3 and run this file again.
pause
exit /b 1

:use_py
py -3 -m unittest discover -s tests -p "test_*.py" -v
set "EXIT_CODE=%ERRORLEVEL%"
goto :done

:use_python
python -m unittest discover -s tests -p "test_*.py" -v
set "EXIT_CODE=%ERRORLEVEL%"

:done
if not "%EXIT_CODE%"=="0" pause
endlocal & exit /b %EXIT_CODE%
