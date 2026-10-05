param([string]$ReportDir)
$ErrorActionPreference = 'Stop'
$cwd = (Get-Location).Path
$target = Join-Path $cwd 'work\ceres-v2\09\test-receipts\ui-orders-c417efc3a8464096a788c887ebf5e6b9\effective-attempt-d2d5f0651ee94bb0a80f14f7fa302826\run_service_cleanup.py'
$python = Join-Path $cwd 'backend\.venv\Scripts\python.exe'
$helper = Join-Path $ReportDir 'parse_cleanup_wrapper_once.py'
$shaBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
$stdoutPath = Join-Path $ReportDir 'python-cleanup-wrapper-ast.stdout.raw.txt'
$stderrPath = Join-Path $ReportDir 'python-cleanup-wrapper-ast.stderr.raw.txt'
$commandPath = Join-Path $ReportDir 'python-cleanup-wrapper-ast.command.json'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$started = [DateTime]::UtcNow.ToString('o')
& $python -X utf8 $helper $target 1> $stdoutPath 2> $stderrPath
$exit = $LASTEXITCODE
$finished = [DateTime]::UtcNow.ToString('o')
$shaAfter = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
$receipt = [pscustomobject]@{ started_utc=$started; finished_utc=$finished; argv=@($python,'-X','utf8',$helper,$target); cwd=$cwd; python_executable=$python; environment=@{PYTHONUTF8='1';PYTHONDONTWRITEBYTECODE='1'}; source_path=$target; source_sha256_before=$shaBefore; source_sha256_after=$shaAfter; exit_code=$exit; stdout_file=$stdoutPath; stderr_file=$stderrPath }
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $commandPath -Encoding utf8
$receipt | ConvertTo-Json -Depth 5
Get-Content -LiteralPath $stdoutPath -Raw
if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw }
exit $exit
