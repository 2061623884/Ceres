$ErrorActionPreference='Stop'
$root=(Get-Location).Path
$run=Join-Path $root 'work\ceres-v2-test-env\09-final-candidate-83f1c39408e649a495c633c23a4bbe4c'
$node='C:\Program Files\nodejs\node.exe'
$modules=Join-Path $root 'Ceres\frontend\node_modules'
$tsc=Join-Path $modules 'typescript\bin\tsc'
$vite=Join-Path $modules 'vite\bin\vite.js'
$shim=Join-Path $run 'vite-config-globals.cjs'
Set-Content -LiteralPath $shim -Value 'globalThis.__dirname = process.env.CERES_FRONTEND_DIR;' -Encoding utf8
$reports=@()
foreach($name in @('cold-1','cold-2')){
  $frontend=Join-Path (Join-Path $run $name) 'frontend'
  $dist=Join-Path $run ($name+'-frontend-dist')
  New-Item -ItemType Directory -Force -Path $dist | Out-Null
  $original=@{}
  $unsetKeys=@('NODE_ENV','OPENAI_API_KEY','EMBEDDING_API_KEY','INTERNAL_ADMIN_TOKEN','FIGMA_PUBLIC_URL')
  foreach($key in $unsetKeys){$original[$key]=[Environment]::GetEnvironmentVariable($key,'Process');[Environment]::SetEnvironmentVariable($key,$null,'Process')}
  $viteKeys=@(Get-ChildItem Env: | Where-Object {$_.Name.StartsWith('VITE_')} | ForEach-Object {$_.Name})
  foreach($key in $viteKeys){$original[$key]=[Environment]::GetEnvironmentVariable($key,'Process');[Environment]::SetEnvironmentVariable($key,$null,'Process')}
  $env:CERES_FRONTEND_DIR=$frontend
  $env:FIGMA_PUBLIC_URL=''
  $baseEnv=[ordered]@{unset=$unsetKeys;unsetPrefix='VITE_';FIGMA_PUBLIC_URL='';CERES_FRONTEND_DIR=$frontend;nodeVersion=((& $node --version) | Out-String).Trim();nodeModules=$modules+' via clone junction'}
  $tsArgs=@($tsc,'--noEmit','--project',(Join-Path $frontend 'tsconfig.json'),'--pretty','false')
  $tsOut=Join-Path $run ($name+'-tsc.stdout.txt'); $tsErr=Join-Path $run ($name+'-tsc.stderr.txt')
  $tsStart=(Get-Date).ToUniversalTime().ToString('o')
  Push-Location $frontend
  & $node @tsArgs 1> $tsOut 2> $tsErr
  $tsExit=$LASTEXITCODE
  Pop-Location
  $tsEnd=(Get-Date).ToUniversalTime().ToString('o')
  Set-Content -LiteralPath (Join-Path $run ($name+'-tsc.exit-code.txt')) -Value $tsExit -Encoding ascii
  $tsRecord=[ordered]@{startUtc=$tsStart;endUtc=$tsEnd;executable=$node;argv=$tsArgs;cwd=$frontend;env=$baseEnv;exit=$tsExit;stdoutFile=$tsOut;stderrFile=$tsErr}
  Set-Content -LiteralPath (Join-Path $run ($name+'-tsc.command.json')) -Value ($tsRecord|ConvertTo-Json -Depth 8) -Encoding utf8
  $viteArgs=@('--require',$shim,$vite,'build','--configLoader','runner','--outDir',$dist)
  $viteOut=Join-Path $run ($name+'-vite.stdout.txt'); $viteErr=Join-Path $run ($name+'-vite.stderr.txt')
  $viteStart=(Get-Date).ToUniversalTime().ToString('o')
  Push-Location $frontend
  & $node @viteArgs 1> $viteOut 2> $viteErr
  $viteExit=$LASTEXITCODE
  Pop-Location
  $viteEnd=(Get-Date).ToUniversalTime().ToString('o')
  Set-Content -LiteralPath (Join-Path $run ($name+'-vite.exit-code.txt')) -Value $viteExit -Encoding ascii
  $viteRecord=[ordered]@{startUtc=$viteStart;endUtc=$viteEnd;executable=$node;argv=$viteArgs;cwd=$frontend;env=$baseEnv;exit=$viteExit;stdoutFile=$viteOut;stderrFile=$viteErr;externalDist=$dist}
  Set-Content -LiteralPath (Join-Path $run ($name+'-vite.command.json')) -Value ($viteRecord|ConvertTo-Json -Depth 8) -Encoding utf8
  foreach($key in $original.Keys){[Environment]::SetEnvironmentVariable($key,$original[$key],'Process')}
  [Environment]::SetEnvironmentVariable('CERES_FRONTEND_DIR',$null,'Process')
  $reports += [pscustomobject]@{clone=$name;tscExit=$tsExit;tscStdout=(Get-Content -LiteralPath $tsOut -Raw);tscStderr=(Get-Content -LiteralPath $tsErr -Raw);viteExit=$viteExit;viteStdout=(Get-Content -LiteralPath $viteOut -Raw);viteStderr=(Get-Content -LiteralPath $viteErr -Raw);dist=$dist}
}
$out=$reports|ConvertTo-Json -Depth 8
Set-Content -LiteralPath (Join-Path $run 'frontend-summary.json') -Value $out -Encoding utf8
Write-Output $out
if(@($reports|Where-Object {$_.tscExit -ne 0 -or $_.viteExit -ne 0}).Count -gt 0){exit 8}
