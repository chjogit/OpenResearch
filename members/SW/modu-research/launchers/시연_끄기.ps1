# 모두의리서치 시연 끄기 — 화면(Django) 끄기 → 엔진 끄기
$Root   = 'D:\AI\Projects\2차_모두의리서치_cluade'
$Engine = Join-Path $Root 'modu-research-nodes'
$Screen = Join-Path $Root '_screen_jt\모두의리서치_화면'
Write-Host ""; Write-Host "  모두의리서치 시연을 끕니다"
$n = 0
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*manage.py*runserver 127.0.0.1:*' -and $_.ExecutablePath -like ($Screen + '*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $n++ }
Write-Host ("  화면: " + $(if ($n) { "껐어요" } else { "켜져 있지 않았어요" }))
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'stop.cmd' -WorkingDirectory $Engine -WindowStyle Hidden -Wait
Write-Host "  엔진: 껐어요"
Start-Sleep 2
