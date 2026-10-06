@echo off
REM ==============================================================================
REM scripts/build_windows.bat - 1-Click Windows x64 Build Script for Chalk
REM ==============================================================================

echo ========================================================
echo   CHALK — WINDOWS X64 COMPILATION & PACKAGING PIPELINE
echo ========================================================

cd /d "%~dp0\.."

REM 1. Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ from python.org and ensure "Add Python to PATH" is checked.
    pause
    exit /b 1
)

REM 2. Create or activate virtual environment
if not exist ".venv" (
    echo [*] Creating virtual environment...
    python -m venv .venv
)

echo [*] Activating virtual environment...
call .venv\Scripts\activate.bat

REM 3. Upgrade pip and install dependencies
echo [*] Installing production dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

REM 4. Execute test suite
echo [*] Running test suite...
python -m unittest tests/test_chalk_pipeline.py
if errorlevel 1 (
    echo [ERROR] Unit tests failed. Build aborted.
    pause
    exit /b 1
)

REM 5. Compile standalone executable with PyInstaller
echo [*] Compiling standalone executable with build_standalone.py...
python build_standalone.py
if errorlevel 1 (
    echo [ERROR] PyInstaller compilation failed.
    pause
    exit /b 1
)

REM 6. Create Chalk-Setup.exe copy in dist/
if exist "dist\Chalk.exe" (
    copy /y "dist\Chalk.exe" "dist\Chalk-Setup.exe" >nul
    copy /y "dist\Chalk.exe" "dist\Chalk-Windows.exe" >nul
    echo.
    echo ========================================================
    echo   [SUCCESS] Windows x64 Build Complete!
    echo   Binaries located in:
    echo     - dist\Chalk.exe
    echo     - dist\Chalk-Setup.exe
    echo     - dist\Chalk-Windows.exe
    echo ========================================================
) else (
    echo [ERROR] dist\Chalk.exe not found after compilation.
    pause
    exit /b 1
)

pause
