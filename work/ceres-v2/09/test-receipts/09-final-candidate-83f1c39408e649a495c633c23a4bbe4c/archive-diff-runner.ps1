$ErrorActionPreference='Stop'
$root=(Get-Location).Path
$run=Join-Path $root 'work\ceres-v2-test-env\09-final-candidate-83f1c39408e649a495c633c23a4bbe4c'
$out=Join-Path $run 'archive-diff.raw.txt'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'work\ceres-v2-test-env\09-final-candidate-83f1c39408e649a495c633c23a4bbe4c\archive-diff-check.ps1' *> $out
$code=$LASTEXITCODE
Set-Content -LiteralPath (Join-Path $run 'archive-diff.exit-code.txt') -Value $code -Encoding ascii
Get-Content -LiteralPath $out -Raw
Write-Output "CHECK_EXIT=$code"
exit $code
