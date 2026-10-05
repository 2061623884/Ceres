$ErrorActionPreference = 'Stop'
$files = @(
  'C:\Users\20616\Desktop\Agent\Agent产品\Ceres\work\ceres-v2\09\test-receipts\ui-orders-c417efc3a8464096a788c887ebf5e6b9\effective-attempt-d2d5f0651ee94bb0a80f14f7fa302826\stop_ui_services_exact_pids.ps1',
  'C:\Users\20616\Desktop\Agent\Agent产品\Ceres\work\ceres-v2\09\test-receipts\ui-orders-c417efc3a8464096a788c887ebf5e6b9\effective-attempt-d2d5f0651ee94bb0a80f14f7fa302826\verify_ui_services_stopped.ps1'
)
$failed = $false
foreach ($file in $files) {
  $tokens = $null
  $errors = $null
  [System.Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$errors) | Out-Null
  if ($errors.Count -gt 0) {
    $failed = $true
    foreach ($errorItem in $errors) { [Console]::Error.WriteLine("PARSE_ERROR $file $($errorItem.Extent.StartLineNumber):$($errorItem.Extent.StartColumnNumber) $($errorItem.Message)") }
  } else {
    Write-Output "PARSE_OK $file"
  }
}
if ($failed) { exit 1 }
