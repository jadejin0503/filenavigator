@echo off
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    pip install pyinstaller -q
)
pyinstaller --noconfirm build.spec
if errorlevel 1 (
    pause
    exit /b 1
)
if not exist "PFN_app" mkdir "PFN_app"
copy /Y "dist\PFN.exe" "PFN_app\PFN.exe" >nul
if exist "config.json" copy /Y "config.json" "PFN_app\config.json" >nul
echo Done. Run: PFN_app\PFN.exe
pause
