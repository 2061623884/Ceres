param(
  [Parameter(Mandatory=$true)][string]$Group,
  [Parameter(Mandatory=$true)][string[]]$Targets
)
$ErrorActionPreference = 'Stop'
$root = 'C:\Users\20616\Desktop\Agent\Agent产品\Ceres'
$run = Split-Path -Parent $MyInvocation.MyCommand.Path
$suite = Join-Path $run $Group
$temp = Join-Path $suite 'temp'
$basetemp = Join-Path $suite 'basetemp'
New-Item -ItemType Directory -Path $temp,$basetemp -Force | Out-Null
$baseline = Get-Content -LiteralPath (Join-Path $root 'work\ceres-v3\07\candidate-v3\baseline.json') -Raw | ConvertFrom-Json
function Save-SourceSnapshot([string]$path) {
  $actual = [ordered]@{}
  $mismatches = @()
  foreach ($entry in $baseline.sha256.PSObject.Properties) {
    $full = Join-Path $root $entry.Name
    if (Test-Path -LiteralPath $full -PathType Leaf) {
      $hash = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
      $actual[$entry.Name] = $hash
      if ($hash -ne $entry.Value) { $mismatches += $entry.Name }
    } else {
      $actual[$entry.Name] = $null
      $mismatches += $entry.Name
    }
  }
  $head = (& git -C $root rev-parse HEAD).Trim()
  $catalog = (Get-FileHash -LiteralPath (Join-Path $root 'data\sale_guide.db') -Algorithm SHA256).Hash.ToLowerInvariant()
  $zip = (Get-FileHash -LiteralPath (Join-Path $root 'work\ceres-v3\07\candidate-v3\source.zip') -Algorithm SHA256).Hash.ToLowerInvariant()
  $snapshot = [ordered]@{
    captured_at_utc = [DateTime]::UtcNow.ToString('o')
    git_head = $head
    expected_git_head = $baseline.git_head
    source_zip_sha256 = $zip
    expected_source_zip_sha256 = $baseline.source_zip_sha256
    source_path_count = $actual.Count
    expected_source_path_count = $baseline.source_path_count
    catalog_sha256 = $catalog
    expected_catalog_sha256 = $baseline.source_catalog.sha256
    source_sha256 = $actual
    mismatch_count = $mismatches.Count
    mismatches = $mismatches
  }
  [IO.File]::WriteAllText($path, ($snapshot | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
  return $snapshot
}
$before = Save-SourceSnapshot (Join-Path $suite 'source-before.json')
if ($before.git_head -ne $baseline.git_head -or $before.source_zip_sha256 -ne $baseline.source_zip_sha256 -or $before.catalog_sha256 -ne $baseline.source_catalog.sha256 -or $before.source_path_count -ne 312 -or $before.mismatch_count -ne 0) {
  throw 'candidate-v3 source preflight does not match frozen baseline'
}
$gateKeys = @(Get-ChildItem Env: | Where-Object { $_.Name -like 'CERES_V3*' -or $_.Name -like 'CERES_LIVE_*' } | ForEach-Object { $_.Name })
foreach ($key in $gateKeys) { [Environment]::SetEnvironmentVariable($key, '', 'Process') }
$env:LLM_MODE = 'offline'
$env:MERCURY_LIVE = '0'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$env:CERES_LIVE_MEMORY_ACCEPTANCE = ''
$env:CERES_LIVE_V2_DEMO = ''
$env:CERES_V3_ROUTE_EVIDENCE_DIR = ''
$env:CERES_V3_LIVE_EVIDENCE_DIR = ''
$env:CERES_V3_INDEPENDENT_EVIDENCE_DIR = ''
$env:RETRIEVAL_MODE = 'lexical'
$env:RETRIEVAL_INDEX_DIR = ''
$env:MEMORY_MODEL = ''
$env:TEMP = $temp
$env:TMP = $temp
$argv = @('-X','utf8','-m','pytest','-p','no:cacheprovider','-W','error::pytest.PytestUnhandledThreadExceptionWarning','-vv','--tb=short','-rs','--basetemp',$basetemp) + $Targets
$environment = [ordered]@{
  LLM_MODE = $env:LLM_MODE
  PYTHONDONTWRITEBYTECODE = $env:PYTHONDONTWRITEBYTECODE
  PYTHONUTF8 = $env:PYTHONUTF8
  MERCURY_LIVE = $env:MERCURY_LIVE
  CERES_LIVE_MEMORY_ACCEPTANCE = $env:CERES_LIVE_MEMORY_ACCEPTANCE
  CERES_LIVE_V2_DEMO = $env:CERES_LIVE_V2_DEMO
  CERES_V3_ROUTE_EVIDENCE_DIR = $env:CERES_V3_ROUTE_EVIDENCE_DIR
  CERES_V3_LIVE_EVIDENCE_DIR = $env:CERES_V3_LIVE_EVIDENCE_DIR
  CERES_V3_INDEPENDENT_EVIDENCE_DIR = $env:CERES_V3_INDEPENDENT_EVIDENCE_DIR
  CERES_GATE_KEY_NAMES_BLANKED = $gateKeys
  RETRIEVAL_MODE = $env:RETRIEVAL_MODE
  RETRIEVAL_INDEX_DIR = $env:RETRIEVAL_INDEX_DIR
  MEMORY_MODEL = $env:MEMORY_MODEL
  OPENAI_API_KEY = 'inherited unchanged; value not recorded'
  OPENAI_BASE_URL = 'inherited unchanged; value not recorded'
  LLM_MODEL = 'inherited unchanged; value not recorded'
  TEMP = $temp
  TMP = $temp
}
$command = [ordered]@{
  executable = (Join-Path $root 'backend\.venv\Scripts\python.exe')
  argv = $argv
  cwd = (Join-Path $root 'backend')
  environment = $environment
  group = $Group
  run_dir = $run
  suite_dir = $suite
  basetemp = $basetemp
}
[IO.File]::WriteAllText((Join-Path $suite 'command-environment.json'), ($command | ConvertTo-Json -Depth 9), [Text.UTF8Encoding]::new($false))
$proc = Start-Process -FilePath $command.executable -ArgumentList $argv -WorkingDirectory $command.cwd -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $suite 'stdout.txt') -RedirectStandardError (Join-Path $suite 'stderr.txt')
$start = [ordered]@{
  pid = $proc.Id
  started_at_utc = [DateTime]::UtcNow.ToString('o')
  suite = $Group
  targets = $Targets
  argv = $argv
  cwd = $command.cwd
  run_dir = $run
  suite_dir = $suite
}
[IO.File]::WriteAllText((Join-Path $suite 'process-start.json'), ($start | ConvertTo-Json -Depth 7), [Text.UTF8Encoding]::new($false))
Write-Output "STARTED group=$Group pid=$($proc.Id) run_dir=$run suite_dir=$suite"
$proc.WaitForExit()
$proc.Refresh()
$exitCode = $proc.ExitCode
$after = Save-SourceSnapshot (Join-Path $suite 'source-after.json')
$completion = [ordered]@{
  pid = $proc.Id
  finished_at_utc = [DateTime]::UtcNow.ToString('o')
  exit_code = $exitCode
  suite = $Group
  targets = $Targets
  run_dir = $run
  suite_dir = $suite
  source_path_count = $after.source_path_count
  source_mismatch_count = $after.mismatch_count
  source_zip_sha256 = $after.source_zip_sha256
  catalog_sha256 = $after.catalog_sha256
}
[IO.File]::WriteAllText((Join-Path $suite 'process-completion.json'), ($completion | ConvertTo-Json -Depth 7), [Text.UTF8Encoding]::new($false))
Write-Output "FINISHED group=$Group pid=$($proc.Id) exit_code=$exitCode source_paths=$($after.source_path_count) source_mismatch_count=$($after.mismatch_count)"
Get-Content -LiteralPath (Join-Path $suite 'stdout.txt')
if ((Get-Item -LiteralPath (Join-Path $suite 'stderr.txt')).Length -gt 0) {
  Write-Output 'STDERR:'
  Get-Content -LiteralPath (Join-Path $suite 'stderr.txt')
}