$ErrorActionPreference='Stop'
$root=(Get-Location).Path
$run=Join-Path $root 'work\ceres-v2-test-env\09-final-candidate-83f1c39408e649a495c633c23a4bbe4c'
$python=Join-Path $root 'Ceres\backend\.venv\Scripts\python.exe'
$dbdir=Join-Path $run 'isolated-databases'
New-Item -ItemType Directory -Force -Path $dbdir | Out-Null
$reports=@()
foreach($name in @('cold-1','cold-2')){
  $clone=Join-Path $run $name
  $runtimeDb=Join-Path $dbdir ($name+'-runtime.sqlite3')
  $mercuryDb=Join-Path $dbdir ($name+'-mercury.sqlite3')
  $sourceDb=Join-Path $dbdir ($name+'-no-source.sqlite3')
  $indexRoot=Join-Path $clone 'data\retrieval_index-v2-frozen'
  $baseEnv=@{PYTHONUTF8='1';PYTHONDONTWRITEBYTECODE='1';DATABASE_URL=('sqlite:///'+$runtimeDb.Replace('\','/'));MERCURY_DB_PATH=$mercuryDb;SOURCE_DATABASE_PATH=$sourceDb;LLM_MODE='offline';LLM_MODEL='';MEMORY_MODEL='';OPENAI_API_KEY='';EMBEDDING_API_KEY='';RETRIEVAL_INDEX_DIR='';CERES_LIVE_MEMORY_ACCEPTANCE='';CERES_LIVE_V2_DEMO=''}
  $saved=@{}
  foreach($key in $baseEnv.Keys){$saved[$key]=[Environment]::GetEnvironmentVariable($key,'Process');[Environment]::SetEnvironmentVariable($key,$baseEnv[$key],'Process')}
  $seedOut=Join-Path $run ($name+'-seed.stdout.txt'); $seedErr=Join-Path $run ($name+'-seed.stderr.txt')
  $seedStart=(Get-Date).ToUniversalTime().ToString('o')
  Push-Location $clone
  & $python -X utf8 scripts/seed_runtime.py --fixture-only 1> $seedOut 2> $seedErr
  $seedExit=$LASTEXITCODE
  Pop-Location
  $seedEnd=(Get-Date).ToUniversalTime().ToString('o')
  Set-Content -LiteralPath (Join-Path $run ($name+'-seed.exit-code.txt')) -Value $seedExit -Encoding ascii
  $seedRecord=[ordered]@{startUtc=$seedStart;endUtc=$seedEnd;executable=$python;argv=@('-X','utf8','scripts/seed_runtime.py','--fixture-only');cwd=$clone;env=$baseEnv;database=$runtimeDb;mercuryDb=$mercuryDb;sourceDb=$sourceDb;exit=$seedExit;stdoutFile=$seedOut;stderrFile=$seedErr}
  Set-Content -LiteralPath (Join-Path $run ($name+'-seed.command.json')) -Value ($seedRecord|ConvertTo-Json -Depth 8) -Encoding utf8
  $indexOut=Join-Path $run ($name+'-index.stdout.txt'); $indexErr=Join-Path $run ($name+'-index.stderr.txt')
  $indexStart=(Get-Date).ToUniversalTime().ToString('o')
  Push-Location $clone
  & $python -X utf8 scripts/build_retrieval_index.py --index-root $indexRoot verify --version idx-d3e9873a747cb2d6 1> $indexOut 2> $indexErr
  $indexExit=$LASTEXITCODE
  Pop-Location
  $indexEnd=(Get-Date).ToUniversalTime().ToString('o')
  Set-Content -LiteralPath (Join-Path $run ($name+'-index.exit-code.txt')) -Value $indexExit -Encoding ascii
  $indexRecord=[ordered]@{startUtc=$indexStart;endUtc=$indexEnd;executable=$python;argv=@('-X','utf8','scripts/build_retrieval_index.py','--index-root',$indexRoot,'verify','--version','idx-d3e9873a747cb2d6');cwd=$clone;env=$baseEnv;exit=$indexExit;stdoutFile=$indexOut;stderrFile=$indexErr}
  Set-Content -LiteralPath (Join-Path $run ($name+'-index.command.json')) -Value ($indexRecord|ConvertTo-Json -Depth 8) -Encoding utf8
  foreach($key in $baseEnv.Keys){[Environment]::SetEnvironmentVariable($key,$saved[$key],'Process')}
  $reports += [pscustomobject]@{name=$name;seedExit=$seedExit;seedOutput=(Get-Content -LiteralPath $seedOut -Raw);indexExit=$indexExit;indexOutput=(Get-Content -LiteralPath $indexOut -Raw);stdoutFiles=@($seedOut,$indexOut);stderrFiles=@($seedErr,$indexErr)}
}
$json=$reports|ConvertTo-Json -Depth 8
Set-Content -LiteralPath (Join-Path $run 'seed-index-summary.json') -Value $json -Encoding utf8
Write-Output $json
if(@($reports|Where-Object {$_.seedExit -ne 0 -or $_.indexExit -ne 0}).Count -gt 0){exit 7}
