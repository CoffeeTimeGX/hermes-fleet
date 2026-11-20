<#
.SYNOPSIS
  Set up the Hermes fleet director on a Windows PC.

.DESCRIPTION
  Installs whatever is missing (Git for Windows, Python, Tailscale, Hermes Agent),
  clones or updates the hermes-fleet repository, puts the `fleet` command on your
  PATH and runs `fleet init`. Safe to re-run: it never overwrites your inventory,
  your secrets files or your SSH key.

  Run it in a normal (not administrator) PowerShell window:
    powershell -ExecutionPolicy Bypass -File .\home\install.ps1
  or, before you have a copy of the repository:
    irm https://raw.githubusercontent.com/CoffeeTimeGX/hermes-fleet/main/home/install.ps1 | iex

.PARAMETER RepoDir
  Where the repository lives. Default: the folder this script is in, or
  $HOME\hermes-fleet when the script is run from the web.

.PARAMETER SkipHermes
  Do not install Hermes Agent (fleet init still configures it if it is present).

.PARAMETER SkipTailscale
  Do not install Tailscale.
#>
param(
  [string]$RepoDir = "",
  [switch]$SkipHermes,
  [switch]$SkipTailscale
)

$ErrorActionPreference = 'Stop'
$RepoUrl = 'https://github.com/CoffeeTimeGX/hermes-fleet.git'
$HermesInstaller = 'https://hermes-agent.nousresearch.com/install.ps1'

function Write-Step([string]$Text) { Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Note([string]$Text) { Write-Host "    $Text" }
function Write-Warn([string]$Text) { Write-Host "!!  $Text" -ForegroundColor Yellow }

function Update-SessionPath {
  $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $user = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

function Test-Command([string]$Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Install-Package([string]$Id, [string]$Name) {
  if (-not (Test-Command 'winget')) {
    throw "$Name is missing and winget is not available. Install $Name yourself, then run this script again."
  }
  Write-Step "Installing $Name with winget"
  & winget install --id $Id -e --source winget --accept-package-agreements --accept-source-agreements --silent
  if ($LASTEXITCODE -ne 0) { throw "winget could not install $Name (exit code $LASTEXITCODE)." }
  Update-SessionPath
}

function Find-Python {
  $candidates = @()
  if (Test-Command 'py') {
    try {
      $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
      if ($LASTEXITCODE -eq 0 -and $exe) { $candidates += ($exe | Select-Object -First 1).Trim() }
    } catch { }
  }
  foreach ($name in @('python', 'python3')) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    # Skip the Microsoft Store placeholder, which only opens the Store.
    if ($cmd -and ($cmd.Source -notlike '*\WindowsApps\*')) { $candidates += $cmd.Source }
  }
  foreach ($c in $candidates) {
    try {
      & $c -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
      if ($LASTEXITCODE -eq 0) { return $c }
    } catch { }
  }
  return $null
}

function Find-Hermes {
  $cmd = Get-Command 'hermes' -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $local = Join-Path $env:LOCALAPPDATA 'hermes\bin\hermes.exe'
  if (Test-Path $local) { return $local }
  return $null
}

Write-Host "hermes-fleet: home machine setup for Windows" -ForegroundColor Green

# ---------------------------------------------------------------- prerequisites
Write-Step "Checking prerequisites"
if ([Environment]::OSVersion.Version.Major -lt 10) { throw "Windows 10 or 11 is required." }

if (-not (Test-Command 'git')) { Install-Package 'Git.Git' 'Git for Windows' }
$gitBash = Join-Path $env:ProgramFiles 'Git\bin\bash.exe'
if (Test-Path $gitBash) {
  Write-Note "Git Bash: $gitBash (Hermes runs its terminal commands with it)"
} else {
  Write-Warn "Git Bash was not found at $gitBash. Hermes needs Git for Windows: winget install --id Git.Git -e"
}

$python = Find-Python
if (-not $python) {
  Install-Package 'Python.Python.3.12' 'Python 3.12'
  $python = Find-Python
}
if (-not $python) { throw "Python 3.9 or newer was not found. Install it from python.org, then run this script again." }
Write-Note "Python: $python"

$ssh = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe'
if (-not (Test-Path $ssh)) {
  throw ("The Windows OpenSSH client is missing. Add it in Settings > System > Optional features > " +
         "'OpenSSH Client' (or, in an administrator PowerShell: " +
         "Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0), then run this script again.")
}
Write-Note "OpenSSH client: $ssh"

if (-not $SkipTailscale) {
  $tailscale = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
  if (-not (Test-Path $tailscale)) { Install-Package 'Tailscale.Tailscale' 'Tailscale' }
  Write-Note "Tailscale: installed (sign in from its tray icon if you have not yet)"
}

# ---------------------------------------------------------------- repository
Write-Step "The hermes-fleet repository"
if (-not $RepoDir) {
  if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'bin\fleet'))) {
    $RepoDir = Split-Path -Parent $PSScriptRoot
  } else {
    $RepoDir = Join-Path $HOME 'hermes-fleet'
  }
}
if (Test-Path (Join-Path $RepoDir '.git')) {
  Write-Note "Updating $RepoDir"
  & git -C $RepoDir pull --ff-only
  if ($LASTEXITCODE -ne 0) { Write-Warn "git pull failed; continuing with the copy you have." }
} elseif (Test-Path (Join-Path $RepoDir 'home\bin\fleet')) {
  Write-Note "Using $RepoDir (not a git clone, so it is not updated)"
} else {
  Write-Note "Cloning $RepoUrl into $RepoDir"
  & git clone $RepoUrl $RepoDir
  if ($LASTEXITCODE -ne 0) { throw "git clone failed." }
}
$fleetCli = Join-Path $RepoDir 'home\bin\fleet'

# ---------------------------------------------------------------- Hermes Agent
Write-Step "Hermes Agent"
$hermes = Find-Hermes
if ($hermes) {
  Write-Note "Found $hermes"
} elseif ($SkipHermes) {
  Write-Warn "Hermes is not installed (-SkipHermes). Install it later with: irm $HermesInstaller | iex"
} else {
  Write-Note "Running the official Hermes installer in a separate PowerShell"
  & powershell -NoProfile -ExecutionPolicy Bypass -Command "irm $HermesInstaller | iex"
  Update-SessionPath
  $hermes = Find-Hermes
  if ($hermes) { Write-Note "Installed $hermes" } else { Write-Warn "Hermes did not install. Check the output above, then run this script again." }
}

# ---------------------------------------------------------------- PATH
Write-Step "Putting the fleet command on your PATH"
$localBin = Join-Path $HOME '.local\bin'
New-Item -ItemType Directory -Force -Path $localBin | Out-Null
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$parts = @()
if ($userPath) { $parts = $userPath -split ';' | Where-Object { $_ } }
if ($parts -notcontains $localBin) {
  [Environment]::SetEnvironmentVariable('Path', ((@($parts) + $localBin) -join ';'), 'User')
  Write-Note "Added $localBin to your user PATH"
} else {
  Write-Note "$localBin is already on your PATH"
}
Update-SessionPath

# ---------------------------------------------------------------- fleet init
Write-Step "fleet init"
$initArgs = @($fleetCli, 'init')
if (-not $hermes) { $initArgs += '--no-hermes' }
& $python @initArgs
if ($LASTEXITCODE -ne 0) { throw "fleet init failed (exit code $LASTEXITCODE)." }

Write-Step "Done. Next steps"
Write-Host @"
  1. Open a NEW PowerShell window (so the PATH change applies), then check:
       fleet doctor
  2. Choose the director's model and connect Telegram (docs/home/windows.md, steps 4 and 5):
       hermes -p director model
       hermes -p director gateway setup
       hermes gateway install
       hermes gateway start
  3. Create the scheduled checks:
       fleet hermes-cron
  4. Then set up Tailscale and the VPSs: docs/getting-started.md, steps 2 to 6
     (online: https://coffeetimegx.github.io/hermes-fleet/getting-started/)
"@
