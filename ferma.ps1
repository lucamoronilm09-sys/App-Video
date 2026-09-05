# Ferma AI Video Maker: uccide per command-line (robusto con npm/node figli).
$ErrorActionPreference = "SilentlyContinue"
$root = "App Video"

# Backend: uvicorn del progetto
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*$root*" -and $_.CommandLine -like "*uvicorn*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Frontend: next start + wrapper npm.cmd del progetto
Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
  Where-Object { $_.CommandLine -like "*$root*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" |
  Where-Object { $_.CommandLine -like "*$root*frontend*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Render ffmpeg orfani del progetto (output in data\projects)
Get-CimInstance Win32_Process -Filter "Name='ffmpeg.exe'" |
  Where-Object { $_.CommandLine -like "*$root*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Write-Output "AI Video Maker fermato."
