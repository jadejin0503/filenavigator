@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Build PFN.exe via PyInstaller (ASCII only; avoid encoding issues in cmd.exe)

python -c "import PIL" 1>nul 2>nul
if errorlevel 1 (
    pip install Pillow -q
)

python "%~dp0scripts\build_app_icon_from_png.py"
if errorlevel 1 (
    echo WARNING: failed to generate ICO; keep existing assets\app_icon.ico
)

python -c "import PyInstaller" 1>nul 2>nul
if errorlevel 1 (
    pip install pyinstaller -q
)

if exist "%~dp0build" rmdir /s /q "%~dp0build"
pyinstaller --noconfirm --clean build.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

if not exist "PFN_app" mkdir "PFN_app"
copy /Y "dist\PFN.exe" "PFN_app\PFN.exe" >nul
if exist "config.json" copy /Y "config.json" "PFN_app\config.json" >nul
echo OK. Run: PFN_app\PFN.exe
pause
