param([ValidateSet('start','stop')][string]$Action='start')
$ErrorActionPreference='Stop'
$appRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtime=if($env:MODU_NODES_DATA_DIR){[IO.Path]::GetFullPath($env:MODU_NODES_DATA_DIR)}else{Join-Path $appRoot 'data'}
$port=if($env:MODU_NODES_PORT){[int]$env:MODU_NODES_PORT}else{4395}
if($port -lt 1024 -or $port -gt 65535){throw 'Invalid port'}
$baseUrl="http://127.0.0.1:$port"
if($Action -eq 'stop'){
 $tokenPath=Join-Path $runtime 'stop-token.txt'
 if(-not(Test-Path -LiteralPath $tokenPath)){Write-Output 'This app has no running instance (no stop token).';exit}
 $stopToken=[IO.File]::ReadAllText($tokenPath)
 try{Invoke-RestMethod -Method Post -Uri "$baseUrl/stop" -Headers @{'X-Stop-Token'=$stopToken} | Out-Null;Write-Output "Stopped: $baseUrl"}catch{Write-Output "Not stopped (not running or token mismatch): $($_.Exception.Message)"}
 Remove-Item -LiteralPath $tokenPath -ErrorAction SilentlyContinue
 exit
}
try{$h=Invoke-RestMethod "$baseUrl/api/health" -TimeoutSec 2;if($h.app -eq 'modu-research-nodes'){Write-Output "Already running: $baseUrl";Start-Process $baseUrl;exit};throw 'Port in use'}catch{if($_.Exception.Message -eq 'Port in use'){throw "Port $port is used by another app. Set MODU_NODES_PORT to a free port."}}
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$pythonPath=Join-Path $appRoot '.venv/Scripts/python.exe'
if(-not(Test-Path -LiteralPath $pythonPath)){throw 'Run setup.cmd first'}
$env:MODU_NODES_PORT=[string]$port
$env:MODU_NODES_DATA_DIR=$runtime
$process=Start-Process -FilePath $pythonPath -ArgumentList @('-X','utf8','-m','mrn') -WorkingDirectory $appRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'server.out.log') -RedirectStandardError (Join-Path $runtime 'server.err.log')
for($i=0;$i -lt 50;$i++){
 Start-Sleep -Milliseconds 200
 try{$h=Invoke-RestMethod "$baseUrl/api/health" -TimeoutSec 2;if($h.app -eq 'modu-research-nodes'){Write-Output "Ready: $baseUrl";Start-Process $baseUrl;exit}}catch{}
 if($process.HasExited){throw 'Startup failed: read data/server.err.log'}
}
throw 'Startup timeout'
