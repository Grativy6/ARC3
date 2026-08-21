$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$Builder = Join-Path $RepositoryRoot "scripts/prepare_kaggle_submission.py"

Push-Location $RepositoryRoot
try {
    & python -m uv run --frozen --all-extras --dev --link-mode copy python $Builder @args
    $BuilderExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $BuilderExitCode
