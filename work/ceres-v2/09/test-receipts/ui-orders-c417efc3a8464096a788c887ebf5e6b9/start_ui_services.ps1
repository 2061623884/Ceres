$ErrorActionPreference = 'Stop'
$base = 'C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-test-env\ui-orders-c417efc3a8464096a788c887ebf5e6b9'
$clone = 'C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-test-env\09-corrected-journey-fb5a1006ddc74188903a615f40009b75\cold-journey'
$python = 'C:\Users\20616\Desktop\Agent\Agent产品\Ceres\backend\.venv\Scripts\python.exe'
$node = 'C:\Program Files\nodejs\node.exe'
$frontend = Join-Path $clone 'frontend'
$backend = Join-Path $clone 'backend'
$results = [System.Collections.Generic.List[object]]::new()
foreach ($spec in @(
  @{Host='127.0.0.71'; BackendPort=8111; FrontendPort=5171; Dir=(Join-Path $base 'owner-71'); ViteConfig='vite.ui-owner71.config.ts'},
  @{Host='127.0.0.72'; BackendPort=8112; FrontendPort=5172; Dir=(Join-Path $base 'owner-72'); ViteConfig='vite.ui-owner72.config.ts'}
)) {
  $db = (Join-Path $spec.Dir 'ceres-ui.sqlite3').Replace('\','/')
  $mercuryDb = Join-Path $spec.Dir 'mercury-ui.sqlite3'
  $sourceDb = Join-Path $spec.Dir 'source-not-imported.db'
  $env:PYTHONUTF8 = '1'
  $env:PYTHONDONTWRITEBYTECODE = '1'
  $env:DATABASE_URL = "sqlite:///$db"
  $env:MERCURY_DB_PATH = $mercuryDb
  $env:SOURCE_DATABASE_PATH = $sourceDb
  $env:LLM_MODE = 'offline'
  $env:LLM_MODEL = ''
  $env:MEMORY_MODEL = ''
  $env:OPENAI_BASE_URL = ''
  $env:OPENAI_API_KEY = ''
  $env:RETRIEVAL_INDEX_DIR = ''
  $env:BUSINESS_DATA_MODE = 'demo'
  $apiArgs = @('-X','utf8','-m','uvicorn','app.main:app','--host',$spec.Host,'--port',[string]$spec.BackendPort)
  $apiOut = Join-Path $spec.Dir 'backend.stdout.log'
  $apiErr = Join-Path $spec.Dir 'backend.stderr.log'
  $api = Start-Process -FilePath $python -ArgumentList $apiArgs -WorkingDirectory $backend -WindowStyle Hidden -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr -PassThru
  $apiReceipt = [pscustomobject]@{
    utc = [DateTime]::UtcNow.ToString('o'); executable = $python; argv = @('-X','utf8','-m','uvicorn','app.main:app','--host',$spec.Host,'--port',[string]$spec.BackendPort); cwd=$backend; pid=$api.Id; host=$spec.Host; port=$spec.BackendPort; database=$db; log_out=$apiOut; log_err=$apiErr; environment=[ordered]@{PYTHONUTF8='1';PYTHONDONTWRITEBYTECODE='1';DATABASE_URL="sqlite:///$db";MERCURY_DB_PATH=$mercuryDb;SOURCE_DATABASE_PATH=$sourceDb;LLM_MODE='offline';LLM_MODEL='';MEMORY_MODEL='';OPENAI_BASE_URL='';OPENAI_API_KEY='';RETRIEVAL_INDEX_DIR='';BUSINESS_DATA_MODE='demo'}
  }
  $env:FIGMA_DEV_SERVER_HOST = $spec.Host
  $env:PORT = [string]$spec.FrontendPort
  $viteArgs = @('node_modules/vite/bin/vite.js','--config',$spec.ViteConfig,'--host',$spec.Host,'--port',[string]$spec.FrontendPort,'--strictPort')
  $viteOut = Join-Path $spec.Dir 'frontend.stdout.log'
  $viteErr = Join-Path $spec.Dir 'frontend.stderr.log'
  $vite = Start-Process -FilePath $node -ArgumentList $viteArgs -WorkingDirectory $frontend -WindowStyle Hidden -RedirectStandardOutput $viteOut -RedirectStandardError $viteErr -PassThru
  $viteReceipt = [pscustomobject]@{utc=[DateTime]::UtcNow.ToString('o');executable=$node;argv=$viteArgs;cwd=$frontend;pid=$vite.Id;host=$spec.Host;port=$spec.FrontendPort;config=(Join-Path $frontend $spec.ViteConfig);proxy_target="http://$($spec.Host):$($spec.BackendPort)";log_out=$viteOut;log_err=$viteErr;environment=[ordered]@{FIGMA_DEV_SERVER_HOST=$spec.Host;PORT=[string]$spec.FrontendPort}}
  $results.Add([pscustomobject]@{backend=$apiReceipt;frontend=$viteReceipt})
}
Start-Sleep -Seconds 3
$health = foreach ($item in $results) {
  $apiUri = "http://$($item.backend.host):$($item.backend.port)/openapi.json"
  $uiUri = "http://$($item.frontend.host):$($item.frontend.port)/"
  try { $apiStatus = (Invoke-WebRequest -Uri $apiUri -TimeoutSec 10 -UseBasicParsing).StatusCode } catch { $apiStatus = "ERROR: $($_.Exception.GetType().Name): $($_.Exception.Message)" }
  try { $uiStatus = (Invoke-WebRequest -Uri $uiUri -TimeoutSec 10 -UseBasicParsing).StatusCode } catch { $uiStatus = "ERROR: $($_.Exception.GetType().Name): $($_.Exception.Message)" }
  [pscustomobject]@{host=$item.backend.host;api=$apiStatus;frontend=$uiStatus;backend_pid=$item.backend.pid;frontend_pid=$item.frontend.pid}
}
$record = [pscustomobject]@{started_utc=$results[0].backend.utc;checked_utc=[DateTime]::UtcNow.ToString('o');services=$results;health=$health}
$record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $base 'ui-services.receipt.json') -Encoding utf8
$record | ConvertTo-Json -Depth 8
