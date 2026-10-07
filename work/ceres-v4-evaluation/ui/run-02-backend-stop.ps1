$ErrorActionPreference = 'Stop'
$oldListener = @(Get-NetTCPConnection -State Listen -LocalPort 18012)
$protectedListener = @(Get-NetTCPConnection -State Listen -LocalPort 8012)
if ($oldListener.Count -ne 1 -or $oldListener[0].OwningProcess -ne 68440) { throw "18012 listener identity mismatch" }
if ($protectedListener.Count -ne 1 -or $protectedListener[0].OwningProcess -ne 24512) { throw "8012 protected listener identity mismatch" }
$oldProcess = Get-CimInstance Win32_Process -Filter 'ProcessId = 68440'
if ($null -eq $oldProcess -or $oldProcess.CommandLine -notmatch '--port 18012') { throw "18012 process command identity mismatch" }
Write-Output "verified owned backend pid=68440 port=18012; protected pid=24512 port=8012"
Stop-Process -Id 68440 -ErrorAction Stop
Start-Sleep -Seconds 2
$remaining = @(Get-NetTCPConnection -State Listen -LocalPort 18012 -ErrorAction SilentlyContinue)
$protectedAfter = @(Get-NetTCPConnection -State Listen -LocalPort 8012)
if ($remaining.Count -ne 0) { throw "18012 still listening after owned stop" }
if ($protectedAfter.Count -ne 1 -or $protectedAfter[0].OwningProcess -ne 24512) { throw "8012 protected listener changed" }
Write-Output "stopped owned backend; port 18012 clear; protected pid=24512 still owns 8012"