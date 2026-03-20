param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [string]$Label,
        [string[]]$CmdArgs
    )
    Write-Host $Label
    & $CmdArgs[0] $CmdArgs[1..($CmdArgs.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "Falha na etapa: $Label"
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $projectRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python não encontrado no PATH."
}

if ($Clean) {
    Write-Host "Limpando artefatos antigos (build/dist) ..."
    if (Test-Path (Join-Path $projectRoot "build")) {
        Remove-Item -Recurse -Force (Join-Path $projectRoot "build")
    }
    if (Test-Path (Join-Path $projectRoot "dist")) {
        Remove-Item -Recurse -Force (Join-Path $projectRoot "dist")
    }
}

Invoke-Step -Label "Instalando dependências de build ..." -CmdArgs @(
    "python", "-m", "pip", "install", "--upgrade", "pip"
)
Invoke-Step -Label "Instalando requirements-build.txt ..." -CmdArgs @(
    "python", "-m", "pip", "install", "-r", (Join-Path $projectRoot "requirements-build.txt")
)
Invoke-Step -Label "Gerando executável onedir com PyInstaller ..." -CmdArgs @(
    "python",
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name",
    "InterfaceTradutores",
    "--collect-all",
    "tkinterdnd2",
    "--collect-all",
    "UnityPy",
    "--distpath",
    (Join-Path $projectRoot "dist"),
    "--workpath",
    (Join-Path $projectRoot "build"),
    (Join-Path $projectRoot "app.py")
)

$exePath = Join-Path $projectRoot "dist\InterfaceTradutores\InterfaceTradutores.exe"
if (-not (Test-Path $exePath)) {
    throw "Build executado, mas o executável não foi encontrado em: $exePath"
}

Write-Host ""
Write-Host "Build finalizado com sucesso."
Write-Host "Executável: $exePath"
