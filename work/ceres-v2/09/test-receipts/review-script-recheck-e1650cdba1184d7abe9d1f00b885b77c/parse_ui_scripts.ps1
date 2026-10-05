$ErrorActionPreference = 'Stop'
$targets = @(
  @{ Label = 'stop_ui'; Relative = 'work\ceres-v2\09\test-receipts\ui-orders-c417efc3a8464096a788c887ebf5e6b9\effective-attempt-d2d5f0651ee94bb0a80f14f7fa302826\stop_ui_services_exact_pids.ps1' },
  @{ Label = 'verify_ui'; Relative = 'work\ceres-v2\09\test-receipts\ui-orders-c417efc3a8464096a788c887ebf5e6b9\effective-attempt-d2d5f0651ee94bb0a80f14f7fa302826\verify_ui_services_stopped.ps1' }
)
$failed = $false
foreach ($target in $targets) {
  $full = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $target.Relative))
  if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { [Console]::Error.WriteLine("MISSING_TARGET $($target.Label)"); $failed = $true; continue }
  $tokens = $null
  $errors = $null
  [System.Management.Automation.Language.Parser]::ParseFile($full, [ref]$tokens, [ref]$errors) | Out-Null
  if ($errors.Count -gt 0) {
    $failed = $true
    foreach ($errorItem in $errors) { [Console]::Error.WriteLine("PARSE_ERROR $($target.Label) $($errorItem.Extent.StartLineNumber):$($errorItem.Extent.StartColumnNumber) $($errorItem.Message)") }
  } else { Write-Output "PARSE_OK $($target.Label)" }
}
if ($failed) { exit 1 }
