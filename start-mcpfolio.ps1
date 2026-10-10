param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

$repoRoot = $PSScriptRoot
$condaBase = $env:CONDA_ROOT
if (-not $condaBase) {
    $condaBase = Join-Path $env:USERPROFILE 'conda'
}
$condaEnvironment = Join-Path $condaBase 'envs\mcpfolio'
$python = Join-Path $condaEnvironment 'python.exe'
$ollamaDirectory = Join-Path $env:LOCALAPPDATA 'Programs\Ollama'
$dashboardUrl = "http://127.0.0.1:$Port/"

$portListeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($portListeners) {
    $processes = foreach ($processId in ($portListeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
        Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    }
    $mcpfolioProcess = $processes | Where-Object {
        $_.CommandLine -match 'src\.web\.main:app' -and
        $_.ExecutablePath -like '*\envs\mcpfolio\python.exe'
    } | Select-Object -First 1

    if ($mcpfolioProcess) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        } catch {
            $health = $null
        }

        if ($health.status -eq 'healthy') {
            Write-Host "MCPfolio ya responde en el puerto $Port (PID $($mcpfolioProcess.ProcessId)); no iniciaré otra instancia."
            Write-Host 'La salud HTTP no prueba por sí sola que las herramientas MCP estén listas.'
            Start-Process $dashboardUrl
            exit 0
        }
    }

    $owners = ($processes | ForEach-Object { "PID $($_.ProcessId): $($_.Name) $($_.CommandLine)" }) -join '; '
    throw "El puerto $Port ya está ocupado. No terminé ningún proceso. Propietario: $owners"
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "No se encontró el Python del entorno Conda en '$python'."
}

if (-not (Test-Path -LiteralPath (Join-Path $ollamaDirectory 'ollama.exe'))) {
    throw "No se encontró Ollama en '$ollamaDirectory'."
}

$env:Path = "$condaEnvironment;$condaEnvironment\Scripts;$ollamaDirectory;$env:Path"
$env:PYTHONPATH = "$condaEnvironment\Lib\site-packages;$repoRoot"
$env:CONDA_DEFAULT_ENV = 'mcpfolio'
Set-Location -LiteralPath $repoRoot

Write-Host "Iniciando MCPfolio en $dashboardUrl ..."
Start-Process $dashboardUrl
& $python -m uvicorn src.web.main:app --host 127.0.0.1 --port $Port
