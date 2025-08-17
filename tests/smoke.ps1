# tests/smoke.ps1
$base = $env:ODIA_TTS_BASE
if (-not $base) { $base = "http://127.0.0.1:8000" }

# Health
Invoke-RestMethod "$base/health"

# TTS
curl -s -L -o hello.mp3 "$base/speak?text=Hello%20Naija&voice=en-NG-EzinneNeural"
Start-Process hello.mp3

# Agent
$r = Invoke-RestMethod -Method POST -Uri "$base/agent" -ContentType "application/json" -Body (@{ message = "One-line welcome in Nigerian English." } | ConvertTo-Json)
$r
$q = [uri]::EscapeDataString($r.reply)
curl -s -L -o reply.mp3 "$base/speak?text=$q&voice=en-NG-EzinneNeural"
Start-Process reply.mp3
