[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter()]
    [switch]$NoBuild,

    [Parameter()]
    [string]$Image = "tresor-ansible:local",

    [Parameter()]
    [string]$SshSource = "",

    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Command
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$defaultSshSource = "S:\PROJECTS\linux backup\.ssh"
$dockerConfig = Join-Path $repoRoot ".docker-win"

New-Item -ItemType Directory -Force -Path $dockerConfig | Out-Null
$env:DOCKER_CONFIG = $dockerConfig

if ([string]::IsNullOrWhiteSpace($SshSource)) {
    if (-not [string]::IsNullOrWhiteSpace($env:TRESOR_SSH_SOURCE)) {
        $SshSource = $env:TRESOR_SSH_SOURCE
    } else {
        $SshSource = $defaultSshSource
    }
}

if (-not (Test-Path $SshSource)) {
    throw "SSH source directory not found: $SshSource"
}

if (-not $Command -or $Command.Count -eq 0) {
    $Command = @("bash")
}

$docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$passphraseVars = @(
    "TRESOR_SSH_KEY_PASSPHRASE",
    "TRESOR_SSH_PASSPHRASE",
    "TRESOR_VPS_SSH_PASSPHRASE"
)

if (-not (Test-Path $docker)) {
    throw "Docker CLI not found at $docker"
}

& $docker info | Out-Null

if (-not $NoBuild) {
    & $docker build `
        -f (Join-Path $repoRoot "ansible\Dockerfile.ansible") `
        -t $Image `
        $repoRoot
}

$dockerRunArgs = @(
    "run",
    "--rm",
    "-it",
    "-v", "${repoRoot}:/workspace",
    "-v", "${SshSource}:/seed-ssh:ro",
    "-w", "/workspace/ansible"
)

foreach ($name in $passphraseVars) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        $dockerRunArgs += @("-e", "${name}=$value")
    }
}

$dockerRunArgs += $Image
$dockerRunArgs += $Command

& $docker @dockerRunArgs
