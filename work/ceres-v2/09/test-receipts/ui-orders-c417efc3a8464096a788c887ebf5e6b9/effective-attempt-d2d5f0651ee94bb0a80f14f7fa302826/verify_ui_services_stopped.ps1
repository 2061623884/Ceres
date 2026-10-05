param([string]$AttemptPath)
$ErrorActionPreference = 'Stop'
$started = [DateTime]::UtcNow.ToString('o')
$expected = @(
  @{ Id = 41156; Name = 'python.exe'; Parts = @('app.main:app', '--host 127.0.0.71', '--port 8111') },
  @{ Id = 15344; Name = 'node.exe'; Parts = @('vite.ui-owner71.config.ts', '--host 127.0.0.71', '--port 5171') },
  @{ Id = 24468; Name = 'python.exe'; Parts = @('app.main:app', '--host 127.0.0.72', '--port 8112') },
  @{ Id = 39992; Name = 'node.exe'; Parts = @('vite.ui-owner72.config.ts', '--host 127.0.0.72', '--port 5172') }
)
$ids = @($expected | ForEach-Object { $_.Id })
$remaining = @(Get-CimInstance Win32_Process | Where-Object { $ids -contains $_.ProcessId } | Select-Object ProcessId,Name,CommandLine)
$listeners = @(Get-NetTCPConnection -ErrorAction Stop | Where-Object { $_.State -eq 'Listen' -and $_.LocalPort -in @(8111,8112,5171,5172) } | Select-Object LocalAddress,LocalPort,OwningProcess)
$finished = [DateTime]::UtcNow.ToString('o')
$report = [pscustomobject]@{ started_utc=$started; finished_utc=$finished; expected_stopped_pids=$ids; remaining_pids=$remaining; remaining_test_port_listeners=$listeners }
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $AttemptPath 'service-cleanup-verification.json') -Encoding utf8
$report | ConvertTo-Json -Depth 6
if ($remaining.Count -gt 0 -or $listeners.Count -gt 0) { exit 1 }
