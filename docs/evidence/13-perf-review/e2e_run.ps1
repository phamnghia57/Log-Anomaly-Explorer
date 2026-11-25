param(
  [Parameter(Mandatory)][string]$Repo,
  [Parameter(Mandatory)][string]$WorkerPath,
  [Parameter(Mandatory)][string]$Prefix,
  [Parameter(Mandatory)][string]$OutDir,
  [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$ev = "$Repo\docs\evidence\13-perf-review"
New-Item -ItemType Directory -Force $OutDir | Out-Null
Remove-Item "$OutDir\$Prefix-ml.json" -ErrorAction SilentlyContinue

$env:STORAGE_BACKEND = "opensearch"; $env:OPENSEARCH_URL = "http://127.0.0.1:19200"
$env:LOG_INDEX = "$Prefix-logs"; $env:QUARANTINE_INDEX = "$Prefix-logs-quarantine"
$env:RETENTION_INTERVAL_SECONDS = "0"; $env:INGEST_RATE_LIMIT_RPS = "100"
$env:CLUSTER_INDEX = "$Prefix-clusters"; $env:HISTORY_INDEX = "$Prefix-cluster-history"
$env:ML_STATE_PATH = "$OutDir\$Prefix-ml.json"
$env:ALERT_WEBHOOK_URL = ""; $env:HEALTHCHECK_PING_URL = ""
$env:ANOMALY_THRESHOLD = "3.0"; $env:WINDOW_SECONDS = "60"; $env:HISTORY_WINDOWS = "30"
$env:INGESTION_LAG_SECONDS = "10"; $env:INGESTION_URL = "http://127.0.0.1:18000/ingest"
Remove-Item Env:OTEL_EXPORTER_OTLP_ENDPOINT -ErrorAction SilentlyContinue

$procs = @()
try {
  $env:PYTHONPATH = $Repo
  $procs += Start-Process $Python -ArgumentList "-W ignore -m uvicorn ingestion.src.main:app --host 127.0.0.1 --port 18000 --log-level warning" -WorkingDirectory $Repo -PassThru -WindowStyle Hidden -RedirectStandardError "$OutDir\$Prefix-ingestion.err"
  $procs += Start-Process $Python -ArgumentList "-W ignore -m uvicorn demo-app.src.main:app --host 127.0.0.1 --port 18001 --log-level warning" -WorkingDirectory $Repo -PassThru -WindowStyle Hidden -RedirectStandardError "$OutDir\$Prefix-demo.err"
  Start-Sleep 8
  $env:PYTHONPATH = $WorkerPath
  $procs += Start-Process $Python -ArgumentList "-W ignore -m clustering.src.worker" -WorkingDirectory $WorkerPath -PassThru -WindowStyle Hidden -RedirectStandardError "$OutDir\$Prefix-worker.log"
  $env:PYTHONPATH = $Repo
  $storm = Start-Process $Python -ArgumentList "-W ignore `"$ev\storm.py`" --rate 10 --seconds 900" -WorkingDirectory $Repo -PassThru -WindowStyle Hidden -RedirectStandardOutput "$OutDir\$Prefix-storm.json" -RedirectStandardError "$OutDir\$Prefix-storm.err"
  $procs += $storm
  Start-Sleep 200
  & $Python -W ignore "$ev\e2e_probe.py" --prefix $Prefix --trials "runtime:web:30,timeout:mobile:55,connection:web:30" |
    Tee-Object -FilePath "$OutDir\$Prefix-probe.jsonl"
  $storm.WaitForExit(600000) | Out-Null
} finally {
  foreach ($p in $procs) { if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }
}
