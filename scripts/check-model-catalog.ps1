# Run from any directory. Requires Docker and uv; no provider keys required.
param(
    [switch]$RealSandbox,
    [switch]$FullSuite,
    [switch]$Golden,
    [switch]$LiveModels,
    [string[]]$TestFiles = @()
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$containerName = 'asep-catalog-check-' + [guid]::NewGuid().ToString('N').Substring(0, 10)
$initPath = Join-Path $repoRoot 'infra/docker/postgres-init'
$oldDatabase = $env:DATABASE_URL
$oldApiDatabase = $env:DATABASE_URL_API
$oldSuperuser = $env:POSTGRES_SUPERUSER_URL
$oldRealSandbox = $env:ASEP_REAL_SANDBOX
$oldRedis = $env:REDIS_URL
$oldSandbox = $env:SANDBOX_ENABLED
$oldSandboxRequired = $env:SANDBOX_REQUIRED
$started = $false
$redisStarted = $false
try {
    docker run -d --rm --name $containerName -e POSTGRES_PASSWORD=postgres `
        -p '127.0.0.1::5432' --mount "type=bind,source=$initPath,target=/docker-entrypoint-initdb.d,readonly" `
        pgvector/pgvector:pg16 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not start the temporary test database.' }
    $started = $true
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        docker exec $containerName pg_isready -h 127.0.0.1 -U postgres *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Temporary test database did not become ready.' }
    $mapping = docker port $containerName 5432/tcp
    if ($LASTEXITCODE -ne 0 -or $mapping -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw 'Could not determine the test database port.'
    }
    $testPort = $Matches[1]
    docker run -d --rm --name "$containerName-redis" -p '127.0.0.1::6379' redis:7-alpine | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not start the temporary Redis service.' }
    $redisStarted = $true
    $redisMapping = docker port "$containerName-redis" 6379/tcp
    if ($LASTEXITCODE -ne 0 -or $redisMapping -notmatch '^127\.0\.0\.1:(\d+)$') {
        throw 'Could not determine the test Redis port.'
    }
    $redisPort = $Matches[1]
    $env:REDIS_URL = "redis://127.0.0.1:$redisPort/0"
    $env:DATABASE_URL = "postgresql+psycopg://asep:asep@127.0.0.1:$testPort/asep_test"
    $env:DATABASE_URL_API = "postgresql+psycopg://asep_api:asep_api@127.0.0.1:$testPort/asep_test"
    $env:POSTGRES_SUPERUSER_URL = "postgresql://postgres:postgres@127.0.0.1:$testPort/postgres"
    if ($RealSandbox) { $env:ASEP_REAL_SANDBOX = '1' }
    Push-Location (Join-Path $repoRoot 'apps/engine')
    try {
        # Exercise the real migration chain on a different disposable database.
        docker exec $containerName createdb -U postgres -O asep asep_migrations
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the migration check database.' }
        $env:DATABASE_URL = "postgresql+psycopg://asep:asep@127.0.0.1:$testPort/asep_migrations"
        uv run alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'Migration upgrade failed.' }
        uv run alembic downgrade 0025
        if ($LASTEXITCODE -ne 0) { throw 'Migration downgrade failed.' }
        uv run alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'Migration re-upgrade failed.' }
        $env:DATABASE_URL = "postgresql+psycopg://asep:asep@127.0.0.1:$testPort/asep_test"
        $checks = @(
            'tests/test_model_catalog.py', 'tests/test_model_catalog_api.py',
            'tests/test_model_router.py', 'tests/test_agent_registry.py', 'tests/test_llm_retries.py',
            'tests/test_llm_stream_usage.py', 'tests/test_runs_api.py', 'tests/test_qa_loop.py',
            'tests/test_reviewer.py', 'tests/test_sandbox_gate.py', 'tests/test_triage.py',
            'tests/test_quick_runs.py', 'tests/test_product_manager.py', 'tests/test_supervisor.py',
            'tests/test_run_recovery.py', 'tests/test_reporting.py',
            'tests/test_preview_credentials_api.py', 'tests/test_deploy_approval_api.py'
        )
        if ($FullSuite) { $checks = @() }
        elseif ($TestFiles.Count -gt 0) { $checks = $TestFiles }
        uv run pytest @checks -q --tb=short
        if ($LASTEXITCODE -ne 0) { throw 'Model catalog verification failed.' }
        if ($Golden -or $LiveModels) {
            $env:DATABASE_URL = "postgresql+psycopg://asep:asep@127.0.0.1:$testPort/asep_migrations"
            $env:DATABASE_URL_API = "postgresql+psycopg://asep_api:asep_api@127.0.0.1:$testPort/asep_migrations"
            $env:SANDBOX_ENABLED = if ($RealSandbox -or $LiveModels) { '1' } else { '0' }
            $env:SANDBOX_REQUIRED = $env:SANDBOX_ENABLED
            $modelMode = if ($LiveModels) { '--live' } else { '--fake' }
            $reportName = if ($LiveModels) { 'adaptive-golden-live.json' } else { 'adaptive-golden-fake.json' }
            $scorePath = Join-Path $repoRoot "test-results/$reportName"
            uv run python scripts/eval_adaptive_team.py $modelMode --output $scorePath
            if ($LASTEXITCODE -ne 0) { throw 'Adaptive golden verification failed; inspect the scorecard.' }
        }
    } finally { Pop-Location }
} finally {
    $env:DATABASE_URL = $oldDatabase
    $env:DATABASE_URL_API = $oldApiDatabase
    $env:POSTGRES_SUPERUSER_URL = $oldSuperuser
    $env:ASEP_REAL_SANDBOX = $oldRealSandbox
    $env:REDIS_URL = $oldRedis
    $env:SANDBOX_ENABLED = $oldSandbox
    $env:SANDBOX_REQUIRED = $oldSandboxRequired
    if ($redisStarted) { docker stop "$containerName-redis" | Out-Null }
    if ($started) { docker stop $containerName | Out-Null }
}
