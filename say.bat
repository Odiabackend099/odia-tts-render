@echo off
setlocal

rem Usage: say "your text here"
if "%~1"=="" (
  echo Usage: say "text to speak"
  exit /b 1
)

rem Join all args into one string
set "TEXT=%*"

rem URL-encode using PowerShell so spaces & punctuation are safe
for /f "delims=" %%A in ('powershell -NoProfile -Command "[uri]::EscapeDataString(\"%TEXT%\")"') do set "ENC=%%A"

set "VOICE=en-NG-EzinneNeural"
set "BASE=https://odia-tts-render.onrender.com"
set "OUT=hello.mp3"

curl -s -L -o "%OUT%" "%BASE%/speak?text=%ENC%&voice=%VOICE%"

if exist "%OUT%" (
  start "" "%OUT%"
  echo OK: Downloaded and playing "%OUT%"
) else (
  echo ERROR: failed to download audio.
  exit /b 1
)
