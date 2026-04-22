@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM One-file PyInstaller build -> PFN_app\PFN.exe (ASCII-only lines for cmd.exe / GBK)

python -c "import PIL" 1>nul 2>nul
if errorlevel 1 (
    pip install Pillow -q
)

python "%~dp0scripts\build_app_icon_from_png.py"
if errorlevel 1 (
    echo WARNING: failed to generate ICO; keep existing assets\app_icon.ico
)

copy /Y "%~dp0assets\app_icon.ico" "%~dp0icon.ico" >nul

python -c "import PyInstaller" 1>nul 2>nul
if errorlevel 1 (
    pip install pyinstaller -q
)

if exist "%~dp0build" rmdir /s /q "%~dp0build"
if not exist "PFN_app" mkdir "PFN_app"

taskkill /F /IM PFN.exe >nul 2>nul
taskkill /F /IM PFN_portable.exe >nul 2>nul

REM Remove legacy onedir folder and old exes
if exist "%~dp0PFN_app\PFN" rmdir /s /q "%~dp0PFN_app\PFN"
if exist "%~dp0PFN_app\onefile" rmdir /s /q "%~dp0PFN_app\onefile"
if exist "%~dp0PFN_app\PFN.exe" del /f /q "%~dp0PFN_app\PFN.exe" >nul 2>nul
if exist "%~dp0PFN_app\PFN_portable.exe" del /f /q "%~dp0PFN_app\PFN_portable.exe" >nul 2>nul

pyinstaller --noconfirm --clean --distpath "%~dp0PFN_app" --workpath "%~dp0build" "%~dp0build.spec"
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)
if not exist "%~dp0PFN_app\PFN.exe" (
    echo ERROR: Expected output missing: PFN_app\PFN.exe
    exit /b 1
)

if exist "config.json" copy /Y "config.json" "PFN_app\config.json" >nul
copy /Y "icon.ico" "PFN_app\icon.ico" >nul
if exist "%~dp0assets\DISTRIBUTION_zh.txt" copy /Y "%~dp0assets\DISTRIBUTION_zh.txt" "PFN_app\DISTRIBUTION_zh.txt" >nul

echo OK. Output: PFN_app\PFN.exe
exit /b 0
