# 모두의리서치 시연 열기 — 엔진(127.0.0.1:4395) 확인·켜기 → 화면(Django) 켜기 → 브라우저 열기. 모두 이 PC 안에서만(127.0.0.1).
$ErrorActionPreference = 'Stop'
$Root   = 'D:\AI\Projects\2차_모두의리서치_cluade'
$Engine = Join-Path $Root 'modu-research-nodes'
$Screen = Join-Path $Root '_screen_jt\모두의리서치_화면'
$Py     = Join-Path $Screen (".venv-" + $env:COMPUTERNAME + "\Scripts\python.exe")
$Ports  = @(8765, 5180, 8000)            # .env 의 CSRF_TRUSTED_ORIGINS 에 들어 있는 번호만
function Say($m){ Write-Host ("  " + $m) }
function Ok($url){ try { $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2; return $r.StatusCode -lt 500 } catch { return $false } }
function EngineUp(){ try { $h = Invoke-RestMethod 'http://127.0.0.1:4395/api/health' -TimeoutSec 2; return $h.app -eq 'modu-research-nodes' } catch { return $false } }

Write-Host ""; Write-Host "  모두의리서치 시연 화면을 엽니다 (이 PC 안에서만 열림)"; Write-Host ""

# 1) 엔진
if (EngineUp) { Say "엔진: 이미 켜져 있음 (127.0.0.1:4395)" }
else {
  Say "엔진: 켜는 중... (처음엔 20~60초)"
  Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'start.cmd' -WorkingDirectory $Engine -WindowStyle Hidden
  $t = 0; while (-not (EngineUp) -and $t -lt 120) { Start-Sleep 2; $t += 2 }
  if (-not (EngineUp)) { Say "엔진이 120초 안에 켜지지 않았어요. 엔진 폴더의 start.cmd 를 직접 실행해 보세요."; Read-Host "  Enter 로 닫기"; exit 1 }
  Say "엔진: 켜짐"
}

# 1-1) 가격 사본 갱신(연구용, PM 2026-11-15): 엔진을 켠 뒤 뒤에서 한 번. 이미 최신이면 KIS를 부르지 않음. 결과는 _tools\price_refresh\last-result.txt
$Refresh = Join-Path $Root '_tools\price_refresh\price_refresh.py'
if (Test-Path $Refresh) {
  # v0.39.5 (PM 2026-11-16): 가격 갱신이 끝난 뒤 이어서 수급 갱신(Plan B, KIS 투자자별 매매). 둘 다 같은 사본을 바꾸므로 차례로
  $Flow = Join-Path $Root '_tools\flow_refresh\flow_refresh.py'
  $cmd = 'if exist local-env.cmd call local-env.cmd & ".venv\Scripts\python.exe" -X utf8 "' + $Refresh + '" --auto'
  if (Test-Path $Flow) { $cmd += ' & ".venv\Scripts\python.exe" -X utf8 "' + $Flow + '" --auto' }
  Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cmd -WorkingDirectory $Engine -WindowStyle Hidden
  Say "가격·수급 사본: 최신인지 뒤에서 확인합니다(필요하면 KIS 일별 시세·투자자별 매매로 채움)"
}

# 2) 화면
if (-not (Test-Path $Py)) { Say "화면 설치가 아직 안 됐어요(가상환경 없음). 설치 안내 3장을 먼저 해 주세요."; Read-Host "  Enter 로 닫기"; exit 1 }
# T2·T3 (PM 2026-11-15): 가입 동의·AI 사용량 표가 없으면 만든다(이미 있으면 아무것도 안 함)
Push-Location $Screen; & $Py manage.py migrate --noinput | Out-Null; $mig = $LASTEXITCODE; Pop-Location
if ($mig -ne 0) { Say "화면 데이터베이스 준비(migrate)에 실패했어요. 이 창의 글을 알려 주세요."; Read-Host "  Enter 로 닫기"; exit 1 }
$port = $null
foreach ($p in $Ports) { if (Ok "http://127.0.0.1:$p/research/") { $port = $p; Say "화면: 이미 켜져 있음 (127.0.0.1:$p)"; break } }
if (-not $port) {
  foreach ($p in $Ports) {
    try { $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse('127.0.0.1'), $p); $l.Start(); $l.Stop(); $port = $p; break } catch { }
  }
  if (-not $port) { Say ("쓸 수 있는 포트가 없어요(" + ($Ports -join ', ') + "). PowerShell 에서 netsh interface ipv4 show excludedportrange protocol=tcp 결과를 알려 주세요."); Read-Host "  Enter 로 닫기"; exit 1 }
  Say "화면: 켜는 중... (127.0.0.1:$port — 최소화된 창으로 돌아갑니다. 그 창을 닫으면 화면이 꺼져요)"
  Start-Process -FilePath $Py -ArgumentList 'manage.py', 'runserver', "127.0.0.1:$port" -WorkingDirectory $Screen -WindowStyle Minimized
  $t = 0; while (-not (Ok "http://127.0.0.1:$port/research/") -and $t -lt 40) { Start-Sleep 1; $t += 1 }
  if (-not (Ok "http://127.0.0.1:$port/research/")) { Say "화면이 40초 안에 열리지 않았어요. 작업 표시줄의 최소화된 창에 나온 글을 알려 주세요."; Read-Host "  Enter 로 닫기"; exit 1 }
}

# 3) 브라우저
$url = "http://127.0.0.1:$port/research/"
Say "브라우저를 엽니다: $url  (처음 한 번은 Ctrl+F5)"
Start-Process $url
Start-Sleep 3
