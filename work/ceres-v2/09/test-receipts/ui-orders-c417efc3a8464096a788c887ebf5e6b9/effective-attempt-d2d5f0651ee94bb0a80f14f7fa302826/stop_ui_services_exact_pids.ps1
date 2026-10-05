$ErrorActionPreference = 'Stop'
$started = [DateTime]::UtcNow.ToString('o')
$expected = @(
  @{ Id = 41156; Name = 'python.exe'; Parts = @('app.main:app', '--host 127.0.0.71', '--port 8111') },
  @{ Id = 15344; Name = 'node.exe'; Parts = @('vite.ui-owner71.config.ts', '--host 127.0.0.71', '--port 5171') },
  @{ Id = 24468; Name = 'python.exe'; Parts = @('app.main:app', '--host 127.0.0.72', '--port 8112') },
  @{ Id = 39992; Name = 'node.exe'; Parts = @('vite.ui-owner72.config.ts', '--host 127.0.0.72', '--port 5172') }
)
$before = @()
foreach ($item in $expected) {
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($item.Id)"
  if ($null -eq $proc) { throw "Expected isolated PID $($item.Id) is absent before cleanup." }
  if ($proc.Name -ne $item.Name) { throw "PID $($item.Id) name mismatch: $($proc.Name)" }
  foreach ($part in $item.Parts) {
    if ($proc.CommandLine -notmatch [regex]::Escape($part)) { throw "PID $($item.Id) command mismatch; required marker absent: $part" }
  }
  $before += [pscustomobject]@{ pid=$item.Id; name=$proc.Name; command_line=$proc.CommandLine }
}
foreach ($item in $expected) {
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($item.Id)"
  if ($null -eq $proc -or $proc.Name -ne $item.Name) { throw "PID $($item.Id) changed between validation and stop." }
  foreach ($part in $item.Parts) {
    if ($proc.CommandLine -notmatch [regex]::Escape($part)) { throw "PID $($item.Id) command changed before stop." }
  }
  Stop-Process -Id $item.Id -Force
}
Start-Sleep -Milliseconds 500
$ids = @($expected | ForEach-Object { $_.Id })
$remaining = @(Get-CimInstance Win32_Process | Where-Object { $ids -contains $_.ProcessId } | Select-Object ProcessId,Name,CommandLine)
$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in @(8111,8112,5171,5172) } | Select-Object LocalAddress,LocalPort,OwningProcess)
$finished = [DateTime]::UtcNow.ToString('o')
$report = [pscustomobject]@{ started_utc=$started; finished_utc=$finished; expected=$expected; verified_before=$before; remaining_pids=$remaining; remaining_test_port_listeners=$listeners }
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $attempt 'service-cleanup.json') -Encoding utf8
$report | ConvertTo-Json -Depth 6
if ($remaining.Count -gt 0 -or $listeners.Count -gt 0) { exit 1 }
