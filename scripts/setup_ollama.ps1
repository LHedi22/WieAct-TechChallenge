# Set up local models for dev (never used in production or the demo — docs/DECISIONS.md).
# Usage (PowerShell, repo root):  powershell -ExecutionPolicy Bypass -File scripts\setup_ollama.ps1
# Checks the install, sets the Ollama env vars for your user, pulls the models named in .env
# (LOCAL_MODEL_COMPACT / LOCAL_MODEL_MID / LOCAL_EMBEDDING_MODEL, or the defaults), warms them up,
# then runs `python scripts/llm.py check --provider local`.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama is not installed. Install it with:  winget install Ollama.Ollama" -ForegroundColor Yellow
    exit 1
}

# Two parallel requests (same limiter as the platform), 8k context, keep models loaded 30 min.
$vars = @{ OLLAMA_NUM_PARALLEL = "2"; OLLAMA_CONTEXT_LENGTH = "8192"; OLLAMA_KEEP_ALIVE = "30m" }
$changed = $false
foreach ($name in $vars.Keys) {
    if ([Environment]::GetEnvironmentVariable($name, "User") -ne $vars[$name]) {
        [Environment]::SetEnvironmentVariable($name, $vars[$name], "User")
        $changed = $true
    }
}
if ($changed) { Write-Host "Set OLLAMA_* user variables - restart Ollama (tray icon > Quit, then start it) to apply." -ForegroundColor Yellow }

# Model names from .env (only the LOCAL_* model lines are read), else defaults by RAM.
$ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$models = @{ LOCAL_MODEL_COMPACT = "qwen3:1.7b"; LOCAL_MODEL_MID = $(if ($ramGb -lt 16) { "qwen3:8b" } else { "qwen3:14b" }); LOCAL_EMBEDDING_MODEL = "bge-m3" }
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^(LOCAL_MODEL_COMPACT|LOCAL_MODEL_MID|LOCAL_EMBEDDING_MODEL)=(.+)$') { $models[$Matches[1]] = $Matches[2].Trim() }
    }
}
Write-Host "RAM $ramGb GB - models: $($models.Values -join ', ')"

try { Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 5 | Out-Null }
catch { Write-Host "Ollama is not answering on 127.0.0.1:11434 - start the Ollama app, then rerun." -ForegroundColor Yellow; exit 1 }

foreach ($m in $models.Values) {
    Write-Host "ollama pull $m"
    ollama pull $m
    if ($LASTEXITCODE -ne 0) { Write-Host "pull failed: $m" -ForegroundColor Red; exit 1 }
}

# Warm up the chat models so the first job doesn't pay the load time.
foreach ($key in "LOCAL_MODEL_COMPACT", "LOCAL_MODEL_MID") {
    $body = @{ model = $models[$key]; prompt = "Say OK. /no_think"; stream = $false; keep_alive = "30m" } | ConvertTo-Json
    $t = Measure-Command { Invoke-RestMethod http://127.0.0.1:11434/api/generate -Method Post -Body $body -ContentType "application/json" -TimeoutSec 600 | Out-Null }
    Write-Host ("warmed {0} in {1:N1} s" -f $models[$key], $t.TotalSeconds)
}

python (Join-Path $root "scripts\llm.py") check --provider local
