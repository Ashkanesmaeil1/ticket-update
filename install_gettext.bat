@echo off
echo Installing gettext tools for Windows...

REM Create temp directory
mkdir temp_gettext 2>nul
cd temp_gettext

REM Download gettext for Windows
echo Downloading gettext...
powershell -Command "Invoke-WebRequest -Uri 'https://github.com/mlocati/gettext-iconv-windows/releases/download/v0.21.1-v1.16/gettext0.21.1-v1.16.7z' -OutFile 'gettext.7z'"

REM Check if download was successful
if not exist gettext.7z (
    echo Failed to download gettext. Please check your internet connection.
    pause
    exit /b 1
)

REM Extract the archive
echo Extracting gettext...
powershell -Command "Expand-Archive -Path 'gettext.7z' -DestinationPath '.' -Force"

REM Find the extracted directory
for /d %%i in (gettext-*) do set GETTEXT_DIR=%%i

REM Copy files to a system directory
echo Installing gettext to C:\gettext...
if not exist C:\gettext mkdir C:\gettext
xcopy "%GETTEXT_DIR%\bin\*" "C:\gettext\" /Y /E

REM Add to PATH
echo Adding gettext to PATH...
setx PATH "%PATH%;C:\gettext"

REM Clean up
cd ..
rmdir /s /q temp_gettext

echo.
echo gettext installation completed!
echo Please restart your command prompt for PATH changes to take effect.
echo.
pause 