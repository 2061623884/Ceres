$ErrorActionPreference='Stop'
$root=(Get-Location).Path
$run=Join-Path $root 'work\ceres-v2-test-env\09-final-candidate-83f1c39408e649a495c633c23a4bbe4c'
$manifest=Get-Content -LiteralPath (Join-Path $root 'Ceres\work\ceres-v2\09\source-inputs.json') -Raw | ConvertFrom-Json
$rows=@(foreach($p in $manifest.files.PSObject.Properties){[pscustomobject]@{path=$p.Name;sha=$p.Value}})
$sourceEnv=Join-Path $root 'Ceres\.env'
$nodeModulesTarget=Join-Path $root 'Ceres\frontend\node_modules'
$started=(Get-Date).ToUniversalTime().ToString('o')
$reports=@()
foreach($name in @('cold-1','cold-2')){
  $clone=Join-Path $run $name
  $missing=@(); $mismatch=@()
  foreach($row in $rows){
    $file=Join-Path $clone ($row.path.Replace('/','\'))
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){$missing += $row.path; continue}
    $actual=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLower()
    if($actual -ne $row.sha){$mismatch += $row.path}
  }
  if(-not (Test-Path -LiteralPath $sourceEnv -PathType Leaf)){throw 'Ceres root .env not found; refusing to copy another file'}
  Copy-Item -LiteralPath $sourceEnv -Destination (Join-Path $clone '.env') -Force
  $junction=Join-Path $clone 'frontend\node_modules'
  if(-not (Test-Path -LiteralPath $junction)) { New-Item -ItemType Junction -Path $junction -Target $nodeModulesTarget | Out-Null }
  $reports += [pscustomobject]@{clone=$clone;manifestCount=$rows.Count;missingCount=$missing.Count;mismatchCount=$mismatch.Count;missing=$missing;mismatch=$mismatch;siteJsonPresent=(Test-Path -LiteralPath (Join-Path $clone 'frontend\.figma\make\site.json') -PathType Leaf);rootEnvCopied=(Test-Path -LiteralPath (Join-Path $clone '.env') -PathType Leaf);frontendNodeModulesTarget=$nodeModulesTarget}
}
$pass=(@($reports | Where-Object {$_.manifestCount -ne 412 -or $_.missingCount -ne 0 -or $_.mismatchCount -ne 0 -or -not $_.siteJsonPresent -or -not $_.rootEnvCopied}).Count -eq 0)
$out=[ordered]@{startUtc=$started;endUtc=(Get-Date).ToUniversalTime().ToString('o');manifestFiles=$rows.Count;clones=$reports;pass=$pass}
$json=$out|ConvertTo-Json -Depth 8
Set-Content -LiteralPath (Join-Path $run 'clone-integrity.json') -Value $json -Encoding utf8
Write-Output $json
if(-not $pass){exit 6}
