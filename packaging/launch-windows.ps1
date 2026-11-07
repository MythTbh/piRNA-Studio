param(
    [switch]$SetupOnly,
    [switch]$NoBrowser,
    [ValidateRange(1, 65535)][int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
# PowerShell 5.1's per-byte progress UI makes large downloads much slower.
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
if (-not [Environment]::Is64BitOperatingSystem) { throw 'piRNA Studio requires 64-bit Windows.' }
if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'This installer targets Intel/AMD 64-bit Windows. Native ARM64 Windows is not yet supported.' }
$runtime = Join-Path $root '.runtime'
$prefix = Join-Path $runtime 'env'
$python = Join-Path $prefix 'python.exe'
$perlRoot = Join-Path $runtime 'strawberry'
$env:PYTHONUTF8 = '1'
$env:PIRNA_ORCHESTRATOR = 'direct'
$env:PATH = "$prefix;$prefix\Scripts;$prefix\Library\bin;$perlRoot\perl\bin;$perlRoot\c\bin;" + $env:PATH
$env:DUSTER_PL = Join-Path $root '.tools\TBr2_duster.pl'
$env:SRNAMAPPER_PL = Join-Path $root '.tools\sRNAmapper.pl'
$env:PROTRAC_PL = Join-Path $root '.tools\proTRAC_2.4.2.pl'

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    Write-Host "Running: $Program $($Arguments -join ' ')"
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $Program" }
}
function Get-VerifiedDownload {
    param([string]$Url, [string]$File, [string]$Sha256)
    if ((Test-Path -LiteralPath $File) -and ((Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash -eq $Sha256)) { return }
    $partial = "$File.part"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Write-Host "Downloading $(Split-Path -Leaf $File)..."
            # Use Windows' bundled curl rather than .NET's buffered download path.
            Invoke-Checked 'curl.exe' @('--fail', '--location', '--retry', '2', '--connect-timeout', '30', '--max-time', '300', '--output', $partial, $Url)
            Write-Host 'Verifying download checksum...'
            if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $Sha256) { throw 'Download checksum mismatch.' }
            Move-Item -LiteralPath $partial -Destination $File -Force
            return
        } catch {
            Remove-Item -LiteralPath $partial -ErrorAction SilentlyContinue
            if ($attempt -eq 3) { throw }
            Start-Sleep -Seconds 2
        }
    }
}

$ready = $false
if (Test-Path -LiteralPath $python) {
    & $python packaging/check_runtime.py
    $ready = $LASTEXITCODE -eq 0
}
if (-not $ready) {
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    # FileShare.None prevents two installers changing the same environment.
    $lock = [IO.File]::Open((Join-Path $runtime 'setup-windows.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $transcribing = $false
    try {
        Start-Transcript -Path (Join-Path $runtime 'setup-windows.log') -Append | Out-Null
        $transcribing = $true
        Write-Host 'First launch: installing local research dependencies. Internet and several minutes are required.'
        Write-Host 'No Docker, WSL, Python installation, or administrator password is required.'
        $pythonArchive = Join-Path $runtime 'python-3.12.10-win64.zip'
        Get-VerifiedDownload 'https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg' $pythonArchive '0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8'
        if (-not (Test-Path -LiteralPath $python)) {
            Write-Host 'Extracting the official Python runtime...'
            $unpacked = Join-Path $runtime 'python-package'
            Expand-Archive -LiteralPath $pythonArchive -DestinationPath $unpacked -Force
            New-Item -ItemType Directory -Path $prefix -Force | Out-Null
            Get-ChildItem -LiteralPath (Join-Path $unpacked 'tools') | Copy-Item -Destination $prefix -Recurse -Force
        }
        Invoke-Checked $python @('-m', 'ensurepip', '--upgrade')
        $perlArchive = Join-Path $runtime 'strawberry-perl-5.32.1.1.zip'
        Get-VerifiedDownload 'https://strawberryperl.com/download/5.32.1.1/strawberry-perl-5.32.1.1-64bit-portable.zip' $perlArchive '692646105b0f5e058198a852dc52a48f1cebcaf676d63bbdeae12f4eaee9bf5c'
        if (-not (Test-Path -LiteralPath (Join-Path $perlRoot 'perl\bin\perl.exe'))) {
            Write-Host 'Extracting portable Perl...'
            Expand-Archive -LiteralPath $perlArchive -DestinationPath $perlRoot -Force
        }
        $env:PIP_CACHE_DIR = Join-Path $runtime 'pip-cache'
        Invoke-Checked $python @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'packaging/requirements.txt')
        Invoke-Checked $python @('packaging/install_tools.py', '.tools')
        Invoke-Checked $python @('packaging/check_runtime.py')
        Write-Host 'Setup complete. Later launches reuse these dependencies.'
    } finally {
        if ($transcribing) { Stop-Transcript | Out-Null }
        $lock.Dispose()
    }
}
if ($SetupOnly) { exit 0 }
$serverArgs = @('-m', 'server', '--port', "$Port")
if (-not $NoBrowser) { $serverArgs += '--open-browser' }
Write-Host "Keep this window open while using http://127.0.0.1:$Port . Press Ctrl+C to stop."
Invoke-Checked $python $serverArgs
