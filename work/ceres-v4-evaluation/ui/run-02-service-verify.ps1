$ErrorActionPreference = 'Stop'
$receiptPath = Join-Path $uiDir 'runtime-receipt-run02.json'
$databasePath = Join-Path $uiDir 'runtime-run02.sqlite3'
$vitePath = 'C:\Users\20616\Desktop\Agent\Agent产品\Ceres\work\ceres-v4-evaluation\ui-vite.config.mjs'
$candidateBackend = 'C:\Users\20616\Desktop\Agent\Agent产品\Ceres\work\.ceres-next-08\backend'
$startInfo = Get-Content -Raw (Join-Path $uiDir 'run-02-backend.start.json') | ConvertFrom-Json
$startup = (Get-Content -Raw (Join-Path $uiDir 'run-02-backend.stdout.txt') | ConvertFrom-Json)
$listeners = @(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in @(18012,18443,8012) })
$backendListener = @($listeners | Where-Object LocalPort -eq 18012)
$frontendListener = @($listeners | Where-Object LocalPort -eq 18443)
$protectedListener = @($listeners | Where-Object LocalPort -eq 8012)
if ($backendListener.Count -ne 1 -or $backendListener[0].OwningProcess -ne $startup.startup_pid) { throw 'backend listener/startup pid mismatch' }
if ($frontendListener.Count -ne 1 -or $frontendListener[0].OwningProcess -ne 26128) { throw 'frontend listener identity mismatch' }
if ($protectedListener.Count -ne 1 -or $protectedListener[0].OwningProcess -ne 24512) { throw 'protected 8012 listener changed' }
if ($startup.llm_mode -ne 'live' -or $startup.business_data_mode -ne 'demo' -or $startup.retrieval_mode -ne 'lexical') { throw 'runtime mode mismatch' }
if ($startup.database_url -ne 'sqlite:///C:/Users/20616/Desktop/Agent/Agent产品/Ceres/work/ceres-v4-evaluation/ui/runtime-run02.sqlite3') { throw 'isolated DB mismatch' }
if ($startup.app_module_path -ne (Join-Path $candidateBackend 'app\main.py')) { throw 'backend module path mismatch' }
$backendProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($startup.startup_pid)"
$frontendProcess = Get-CimInstance Win32_Process -Filter 'ProcessId = 26128'
$protectedProcess = Get-CimInstance Win32_Process -Filter 'ProcessId = 24512'
if ($null -eq $backendProcess -or $backendProcess.CommandLine -notmatch '-c') { throw 'backend process command line missing -c' }
if ($null -eq $frontendProcess -or $frontendProcess.CommandLine -notlike ('*' + $vitePath + '*')) { throw 'frontend command line does not identify override Vite config' }
if ($null -eq $protectedProcess) { throw 'protected 8012 process missing' }
$client = [System.Net.Http.HttpClient]::new()
$healthResponse = $client.GetAsync('http://127.0.0.1:18012/health').GetAwaiter().GetResult()
if (-not $healthResponse.IsSuccessStatusCode) { throw "backend health status $([int]$healthResponse.StatusCode)" }
$healthBody = $healthResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult()
$moduleResponse = $client.GetAsync('http://127.0.0.1:18443/src/App.tsx').GetAwaiter().GetResult()
if (-not $moduleResponse.IsSuccessStatusCode) { throw "served App module status $([int]$moduleResponse.StatusCode)" }
$moduleBytes = $moduleResponse.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
$sha = [Security.Cryptography.SHA256]::Create()
$servedAppSha = [BitConverter]::ToString($sha.ComputeHash($moduleBytes)).Replace('-', '').ToLowerInvariant()
$viteSha = (Get-FileHash -LiteralPath $vitePath -Algorithm SHA256).Hash.ToLowerInvariant()
$oldReceipt = Get-Content -Raw (Join-Path $uiDir 'runtime-receipt-run01-snapshot.json') | ConvertFrom-Json -AsHashtable
$oldReceipt.database_path = $databasePath
$oldReceipt.backend_pid = [int]$startup.startup_pid
$oldReceipt.frontend_pid = 26128
$oldReceipt.served_app_module_sha256 = $servedAppSha
$oldReceipt.database_exists = Test-Path -LiteralPath $databasePath
$oldReceipt.vite_config_path = $vitePath
$oldReceipt.vite_config_sha256 = $viteSha
$oldReceipt.proxy_api_target = 'http://127.0.0.1:18012'
$oldReceipt.backend_app_module_path = $startup.app_module_path
$oldReceipt.backend_app_module_sha256 = $startup.app_module_sha256
$oldReceipt.backend_startup_pid = [int]$startup.startup_pid
$oldReceipt.backend_working_directory = $startInfo.working_directory
$oldReceipt.backend_command_line = $backendProcess.CommandLine
$oldReceipt.frontend_command_line = $frontendProcess.CommandLine
$oldReceipt.backend_startup_evidence_path = Join-Path $uiDir 'run-02-backend.stdout.txt'
$oldReceipt.backend_startup_code_sha256 = (Get-FileHash -LiteralPath (Join-Path $uiDir 'run-02-backend-startup-code.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
$oldReceipt.captured_utc = [DateTime]::UtcNow.ToString('o')
[IO.File]::WriteAllText($receiptPath,($oldReceipt | ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
if (Test-Path -LiteralPath (Join-Path $uiDir 'run-02')) { throw 'run-02 output directory already exists' }
$identity = [ordered]@{
  captured_utc=[DateTime]::UtcNow.ToString('o')
  receipt_path=$receiptPath
  receipt_sha256=(Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
  receipt_identity=$oldReceipt
  health_status=[int]$healthResponse.StatusCode
  health_body=$healthBody
  frontend_app_module_status=[int]$moduleResponse.StatusCode
  served_app_module_sha256=$servedAppSha
  backend_listener_pid=[int]$backendListener[0].OwningProcess
  backend_startup_pid=[int]$startup.startup_pid
  frontend_listener_pid=[int]$frontendListener[0].OwningProcess
  protected_8012_pid=[int]$protectedListener[0].OwningProcess
  protected_8012_unchanged=$true
}
$identityPath = Join-Path $uiDir 'run-02-service-identity.json'
[IO.File]::WriteAllText($identityPath,($identity | ConvertTo-Json -Depth 15),[Text.UTF8Encoding]::new($false))
$identity | ConvertTo-Json -Depth 8
$client.Dispose()