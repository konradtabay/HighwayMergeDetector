@echo off
REM Highway Ramp Detection System - Windows Setup Script
REM By Konrad Tabay - tabay.konrad@gmail.com

echo.
echo ======================================================================
echo HIGHWAY RAMP DETECTION SYSTEM - SETUP
echo ======================================================================
echo.
echo Installing dependencies...
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.7+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Install requirements
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo SETUP COMPLETE!
echo ======================================================================
echo.
echo Quick Start:
echo   1. Place GPS files in input/ directory
echo   2. Run: python batch_process_trips.py
echo   3. Visualize: python visualize_server.py
echo.
echo For single trip analysis:
echo   python highway_ramp_detector.py
echo.
echo Documentation: README.md
echo Support: tabay.konrad@gmail.com
echo ======================================================================
echo.
pause

