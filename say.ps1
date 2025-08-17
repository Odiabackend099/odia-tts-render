# say.ps1  — robust “ask & speak” helper for ODIA TTS + Agent

param(
  [Parameter(Mandatory=$true, Position=0)]
  [string]$Text
)

# Config (override by setting env vars before running)
$baseUrl = $env:ODIA_TTS_URL
if (-not $baseUrl) { $baseUrl = "https://odia-tts-render.onrender.com" }

$voice = $env:ODIA_TTS_VOICE
if (-not $voice) { $voice = "en-NG-EzinneNeural" }

function Try-AgentBody {
  param([hashtable]$Body)
  try {
    return Invoke-RestMethod -Method POST "$baseUrl/agent" `
      -Headers @{ "Content-Type" = "application/json" } `
      -Body ($Body | ConvertTo-Json)
  } catch {
    # surface FastAPI error details if present, then return $null so caller can try next shape
    try {
      $resp = $_.Exception.Response
      if ($resp -and $resp.GetResponseStream()) {
        $reader = New-Object IO.StreamReader($resp.GetResponseStream())
        $errBody = $reader.ReadToEnd()
        Write-Host "Agent rejected body $($Body.Keys -join ','): $errBody" -ForegroundColor Yellow
      } else {
        Write-Host "Agent call failed: $($_.Exception.Message)" -ForegroundColor Yellow
      }
    } catch {}
    return $null
  }
}

# 1) Ask the agent, trying multiple payload shapes until one works
$response = $null
$response = Try-AgentBody @{ text    = $Text }
if (-not $response) { $response = Try-AgentBody @{ message = $Text } }
if (-not $response) { $response = Try-AgentBody @{ prompt  = $Text } }

# 2) Extract reply text or fall back to echo
$replyText = $null
if ($response) {
  $replyText = $response.reply
  if (-not $replyText) { $replyText = $response.text }
  if (-not $replyText) { $replyText = $response.message }
  if (-not $replyText) { $replyText = $response.content }
}

if (-not $replyText -or ($replyText -isnot [string]) -or (-not $replyText.Trim())) {
  Write-Host "No reply field found from /agent — falling back to echoing your input." -ForegroundColor Yellow
  $replyText = $Text
}

Write-Host "AI Reply: $replyText" -ForegroundColor Green

# 3) Speak the reply through /speak
$enc = [uri]::EscapeDataString($replyText)
$ttsUrl = "$baseUrl/speak?text=$enc&voice=$voice"

try {
  $outFile = "reply.mp3"
  curl -s -L -o $outFile $ttsUrl
  if ((Test-Path $outFile) -and ((Get-Item $outFile).Length -gt 0)) {
    Write-Host "OK: Downloaded and playing '$outFile' (voice: $voice)" -ForegroundColor Cyan
    start $outFile
  } else {
    Write-Host "TTS returned empty or invalid audio. URL was: $ttsUrl" -ForegroundColor Red
  }
} catch {
  Write-Host "TTS download/playback failed: $($_.Exception.Message)" -ForegroundColor Red
}
