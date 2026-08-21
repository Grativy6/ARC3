[CmdletBinding()]
param(
    [switch] $Check
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PinnedUvVersion = "0.12.5"
$PinnedPythonVersion = "3.12.14"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$script:UvExecutable = $null
$script:UvPython = $null

function Invoke-Uv {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]] $UvArguments
    )

    if ($null -ne $script:UvExecutable) {
        & $script:UvExecutable @UvArguments
    }
    else {
        & $script:UvPython -m uv @UvArguments
    }

    if ($LASTEXITCODE -ne 0) {
        throw "uv failed with exit code $LASTEXITCODE"
    }
}

function Test-UvModule {
    param([string] $PythonExecutable)

    & $PythonExecutable -m uv --version *> $null
    return $LASTEXITCODE -eq 0
}

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($null -ne $uvCommand) {
    $script:UvExecutable = $uvCommand.Source
}
else {
    foreach ($candidate in @("python", "python3", "py")) {
        $pythonCommand = Get-Command $candidate -ErrorAction SilentlyContinue
        if (($null -ne $pythonCommand) -and (Test-UvModule $pythonCommand.Source)) {
            $script:UvPython = $pythonCommand.Source
            break
        }
    }

    if ($null -eq $script:UvPython) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $pythonCommand) {
            $pythonCommand = Get-Command python3 -ErrorAction SilentlyContinue
        }
        if ($null -eq $pythonCommand) {
            $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
        }
        if ($null -eq $pythonCommand) {
            throw "Python is required to install the pinned uv bootstrap dependency."
        }

        $script:UvPython = $pythonCommand.Source
        & $script:UvPython -m pip install --user --disable-pip-version-check "uv==$PinnedUvVersion"
        if ($LASTEXITCODE -ne 0) {
            throw "Installing uv==$PinnedUvVersion failed with exit code $LASTEXITCODE"
        }
    }
}

Push-Location $RepoRoot
try {
    Invoke-Uv python install $PinnedPythonVersion
    Invoke-Uv sync --all-extras --dev --python $PinnedPythonVersion

    if ($Check) {
        Invoke-Uv run ruff check .
        Invoke-Uv run ruff format --check .
        Invoke-Uv run mypy src agent scripts
        Invoke-Uv run pytest -q
        Invoke-Uv run arc3 doctor
    }
}
finally {
    Pop-Location
}
