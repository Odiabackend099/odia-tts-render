Param(
  [Parameter(Mandatory=$true)][string]$Text
)
$base = "https://odia-tts-render.onrender.com"
$q = [uri]::EscapeDataString($Text)
curl -s -L -o hello.mp3 "$base/speak?text=$q&voice=en-NG-EzinneNeural"
Start-Process hello.mp3
