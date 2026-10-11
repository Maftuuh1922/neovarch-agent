# Neovarch Agent installer (Windows x64): the Neovarch core + `neovarch` command + desktop app.
#
#   irm https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/main/scripts/install.ps1 | iex
#
# Core only / uninstall / portable desktop:
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/main/scripts/install.ps1))) -CoreOnly
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/main/scripts/install.ps1))) -Uninstall
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Maftuuh1922/neovrach_Agent/main/scripts/install.ps1))) -Portable
#
# Installs, per user (no admin):
#   * the Neovarch core (original Python agent in core/ of this repo) into
#     %LOCALAPPDATA%\neovarch\neovarch-agent with its own Python + venv (uv);
#   * the `neovarch` command (%LOCALAPPDATA%\Programs\NeovarchAgent\bin\neovarch.cmd, on the user PATH);
#   * the desktop app (NSIS, %LOCALAPPDATA%\Programs\Neovarch Agent; or -Portable);
#   * 9Router (https://9router.com, MIT), the default model provider: `npm install -g 9router`
#     (portable Node.js LTS into %LOCALAPPDATA%\neovarch\tools\node when Node 18+ is missing),
#     started in the background with the free default model oc/big-pickle (no API key).
#     Skip with -No9Router.
#
# Neovarch never uses, reads or changes a Hermes Agent install: no `hermes` command,
# no %LOCALAPPDATA%\hermes or ~\.hermes, no HERMES_HOME. Both can be installed side by side.
#
# Desktop-bootstrap protocol (used by the desktop app on first launch):
#   -Manifest | -Stage <name> [-NonInteractive] [-Json] [-Branch <b>] [-Commit <sha>]
# Environment:
#   NEOVARCH_HOME      data home (default %LOCALAPPDATA%\neovarch)
#   NEOVARCH_VERSION   desktop release tag (e.g. v1.4.6). Default: latest.
#   NEOVARCH_REF       git ref of this repo for the core. Default: NEOVARCH_VERSION or v1.4.6.
#   NEOVARCH_CORE_SRC  local checkout of this repo (or its core\) to install the core from.

param(
    [switch]$Uninstall,
    [switch]$Portable,
    [switch]$CoreOnly,
    [switch]$No9Router,
    [switch]$Manifest,
    [string]$Stage = '',
    [switch]$NonInteractive,
    [switch]$Json,
    [string]$Branch = '',
    [string]$Commit = '',
    [string]$Version = $env:NEOVARCH_VERSION
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with the progress bar on
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

# The core installer must never be steered by a co-installed Hermes.
foreach ($v in 'HERMES_HOME', 'HERMES_DATA_DIR_SUFFIX', 'HERMES_RUNTIME_DIR', 'HERMES_INSTALL_ROOT') {
    Remove-Item "Env:$v" -ErrorAction SilentlyContinue
}

$Repo         = 'Maftuuh1922/neovrach_Agent'
$ReleasesUrl  = "https://github.com/$Repo/releases"
$SetupAsset   = 'neovarch-agent-windows-x64-setup.exe'
$ZipAsset     = 'neovarch-agent-windows-x64.zip'
$AppName      = 'Neovarch Agent'
$ExeName      = 'Neovarch Agent.exe'
$ProcName     = 'Neovarch Agent'
$PyVersion    = '3.14'
$DefaultCoreRef = 'v1.4.6'   # core ref when nothing else is asked for: this installer's release tag
$ReceiptName  = '.neovarch-bootstrap-complete'

$LocalAppData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME 'AppData\Local' }
$NeovarchHome = if ($env:NEOVARCH_HOME) { $env:NEOVARCH_HOME.TrimEnd('\', '/') } else { Join-Path $LocalAppData 'neovarch' }
$CoreDir      = Join-Path $NeovarchHome 'neovarch-agent'
$ToolsDir     = Join-Path $NeovarchHome 'tools'
$Root         = Join-Path $LocalAppData 'Programs\NeovarchAgent'   # bin (+ portable app)
$PortableDir  = Join-Path $Root 'app'
$BinDir       = Join-Path $Root 'bin'
$CliShim      = Join-Path $BinDir 'neovarch.cmd'
$InstallDir   = Join-Path $LocalAppData "Programs\$AppName"         # NSIS install dir
$Uninstaller  = Join-Path $InstallDir "Uninstall $AppName.exe"
$StartMenu    = $null
$DesktopLnk   = $null
$programsDir  = [Environment]::GetFolderPath('Programs')
$desktopDir   = [Environment]::GetFolderPath('Desktop')
if ($programsDir) { $StartMenu  = Join-Path $programsDir "$AppName.lnk" }
if ($desktopDir)  { $DesktopLnk = Join-Path $desktopDir "$AppName.lnk" }
if ($env:NEOVARCH_PORTABLE -eq '1') { $Portable = $true }
$script:CurStage = ''
$script:Uv = $null

function Write-Banner { if (-not $Json) { Write-Host ''; Write-Host $AppName -ForegroundColor Red -NoNewline; Write-Host ' installer' -ForegroundColor DarkGray; Write-Host '' } }
function Write-Step($m) { Write-Host '==> ' -ForegroundColor Red -NoNewline; Write-Host $m }
function Write-Ok($m)   { Write-Host ' ok ' -ForegroundColor Green -NoNewline; Write-Host $m }
function Write-Warn2($m){ Write-Host 'warn ' -ForegroundColor Yellow -NoNewline; Write-Host $m }
function Stop-WithError($m) {
    Write-Host 'error ' -ForegroundColor Red -NoNewline; Write-Host $m
    if ($Json -and $script:CurStage) {
        [Console]::Out.WriteLine((@{ ok = $false; stage = $script:CurStage; reason = "$m" } | ConvertTo-Json -Compress))
    }
    throw $m
}

# Refuse anything that belongs to Hermes Agent.
function Assert-NotHermes($path) {
    $p = [IO.Path]::GetFullPath($path).TrimEnd('\')
    $hermesRoots = @((Join-Path $LocalAppData 'hermes'), (Join-Path $HOME '.hermes')) | ForEach-Object { [IO.Path]::GetFullPath($_).TrimEnd('\') }
    foreach ($r in $hermesRoots) {
        if ($p -ieq $r -or $p.StartsWith("$r\", [StringComparison]::OrdinalIgnoreCase)) { Stop-WithError "refusing to touch $path (belongs to Hermes Agent)" }
    }
    if ((Split-Path $p -Leaf) -match '^hermes(\.exe|\.cmd|-.*)?$') { Stop-WithError "refusing to touch $path (belongs to Hermes Agent)" }
}

function Get-UserPath { $p = [Environment]::GetEnvironmentVariable('Path', 'User'); if ($null -eq $p) { '' } else { $p } }

function Add-ToUserPath($dir) {
    $parts = @((Get-UserPath) -split ';' | Where-Object { $_ -ne '' })
    if ($parts -notcontains $dir) {
        [Environment]::SetEnvironmentVariable('Path', (($parts + $dir) -join ';'), 'User')
        Write-Ok "added $dir to your user PATH"
    }
    if (@($env:Path -split ';') -notcontains $dir) { $env:Path = "$env:Path;$dir" }
}

function Remove-FromUserPath($dir) {
    $parts = @((Get-UserPath) -split ';' | Where-Object { $_ -ne '' })
    if ($parts -contains $dir) {
        [Environment]::SetEnvironmentVariable('Path', (($parts | Where-Object { $_ -ne $dir }) -join ';'), 'User')
        Write-Ok "removed $dir from your user PATH"
    }
}

# ------------------------------------------------------------------ core ---

function Install-Uv {
    $local = Join-Path $ToolsDir 'uv\uv.exe'
    if (Test-Path $local) { $script:Uv = $local; Write-Ok "uv ($local)"; return }
    $onPath = Get-Command uv -ErrorAction SilentlyContinue
    if ($onPath -and ($onPath.Source -notmatch '\\hermes\\|\\\.hermes\\')) { $script:Uv = $onPath.Source; Write-Ok "uv ($($script:Uv))"; return }
    Write-Step "Installing uv into $ToolsDir\uv"
    New-Item -ItemType Directory -Path (Join-Path $ToolsDir 'uv') -Force | Out-Null
    $env:UV_INSTALL_DIR = Join-Path $ToolsDir 'uv'
    $env:UV_UNMANAGED_INSTALL = Join-Path $ToolsDir 'uv'
    $env:UV_NO_MODIFY_PATH = '1'
    $env:INSTALLER_NO_MODIFY_PATH = '1'
    try { Invoke-RestMethod 'https://astral.sh/uv/install.ps1' | Invoke-Expression } catch { Stop-WithError "uv installation failed: $($_.Exception.Message)" }
    if (-not (Test-Path $local)) { Stop-WithError 'uv not available after installation' }
    $script:Uv = $local
    Write-Ok "uv ($local)"
}

function Set-UvEnv {
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $ToolsDir 'python'
    $env:UV_CACHE_DIR = Join-Path $NeovarchHome 'cache\uv'
    $env:UV_TOOL_DIR = Join-Path $ToolsDir 'uv-tools'
    $env:UV_NO_MODIFY_PATH = '1'
}

function Resolve-CoreSource {
    if ($env:NEOVARCH_CORE_SRC) { return $env:NEOVARCH_CORE_SRC }
    if (-not $Commit -and -not $env:NEOVARCH_REF -and $PSCommandPath) {
        $candidate = Join-Path (Split-Path -Parent (Split-Path -Parent $PSCommandPath)) 'core'
        if (Test-Path (Join-Path (Join-Path $candidate 'neovarch') 'cli.py')) { return (Split-Path -Parent $candidate) }
    }
    return $null
}

function Install-CoreFiles {
    Assert-NotHermes $CoreDir
    New-Item -ItemType Directory -Path $NeovarchHome -Force | Out-Null
    $staging = Join-Path $NeovarchHome '.core-staging'
    if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
    $commitSha = ''
    $src = Resolve-CoreSource
    if ($src) {
        if (Test-Path (Join-Path $src 'core')) { $src = Join-Path $src 'core' }
        if (-not (Test-Path (Join-Path (Join-Path $src 'neovarch') 'cli.py'))) { Stop-WithError "NEOVARCH_CORE_SRC has no Neovarch core: $src" }
        Write-Step "Copying the Neovarch core from $src"
        New-Item -ItemType Directory -Path $staging -Force | Out-Null
        Get-ChildItem -Path $src -Force | Where-Object { $_.Name -notin @('venv', '__pycache__', 'node_modules') } |
            Copy-Item -Destination $staging -Recurse -Force
        try { $commitSha = (& git -C $src rev-parse HEAD 2>$null) } catch { $commitSha = '' }
    } else {
        $ref = if ($Commit) { $Commit } elseif ($env:NEOVARCH_REF) { $env:NEOVARCH_REF } elseif ($Branch) { $Branch } elseif ($Version) { $Version } else { $DefaultCoreRef }
        if ($ref -match '^[0-9a-f]{40}$') { $commitSha = $ref }
        $url = "https://codeload.github.com/$Repo/zip/$ref"
        Write-Step "Downloading the Neovarch core ($ref)"
        Write-Host "    $url" -ForegroundColor DarkGray
        $zip = "$staging.zip"; $x = "$staging.x"
        try { Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing } catch { Stop-WithError "core download failed ($url): $($_.Exception.Message)" }
        Expand-Archive -Path $zip -DestinationPath $x -Force
        $top = Get-ChildItem -Path $x -Directory | Select-Object -First 1
        $coreSrc = Join-Path $top.FullName 'core'
        if (-not (Test-Path (Join-Path (Join-Path $coreSrc 'neovarch') 'cli.py'))) { Stop-WithError 'archive has no core\ directory' }
        Move-Item -Path $coreSrc -Destination $staging
        Remove-Item $zip, $x -Recurse -Force -ErrorAction SilentlyContinue
    }
    $venv = Join-Path $CoreDir 'venv'
    if (Test-Path $venv) { Move-Item -Path $venv -Destination (Join-Path $staging 'venv') }
    if (Test-Path $CoreDir) { Remove-Item $CoreDir -Recurse -Force }
    Move-Item -Path $staging -Destination $CoreDir
    if (-not $commitSha) { $commitSha = 'unknown' }
    [IO.File]::WriteAllText((Join-Path $CoreDir '.neovarch-source-commit'), "$commitSha`n")
    Write-Ok "core in $CoreDir"
}

function Install-CorePython {
    if (-not $script:Uv) { Install-Uv }
    Set-UvEnv
    if (-not (Test-Path (Join-Path $CoreDir 'pyproject.toml'))) { Stop-WithError 'core not installed yet (run the core stage first)' }
    Write-Step "Preparing Python $PyVersion and the core's dependencies"
    $venv = Join-Path $CoreDir 'venv'
    $py = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $py)) {
        & $script:Uv venv --quiet --python $PyVersion --python-preference only-managed $venv
        if ($LASTEXITCODE -ne 0) { Stop-WithError "could not create the Python $PyVersion environment" }
    }
    $env:VIRTUAL_ENV = $venv
    & $script:Uv pip install --quiet --python $py -e $CoreDir
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'dependency installation failed' }
    if (-not (Test-Path (Join-Path $venv 'Scripts\neovarch.exe'))) { Stop-WithError 'the neovarch entry point was not created' }
    Write-Ok 'dependencies installed'
}

function Install-CoreCli {
    $exe = Join-Path $CoreDir 'venv\Scripts\neovarch.exe'
    if (-not (Test-Path $exe)) { Stop-WithError 'core environment missing (run the python stage first)' }
    # Installation launcher the desktop resolves (<root>\.neovarch\bin\neovarch.cmd).
    $launcherDir = Join-Path $CoreDir '.neovarch\bin'
    New-Item -ItemType Directory -Path $launcherDir -Force | Out-Null
    $launcher = Join-Path $launcherDir 'neovarch.cmd'
    $body = "@echo off`r`nif not defined NEOVARCH_HOME set `"NEOVARCH_HOME=$NeovarchHome`"`r`n`"$exe`" %*`r`n"
    [IO.File]::WriteAllText($launcher, $body, [Text.Encoding]::ASCII)
    # The one `neovarch` command on PATH.
    Assert-NotHermes $CliShim
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    [IO.File]::WriteAllText($CliShim, "@echo off`r`n`"$launcher`" %*`r`n", [Text.Encoding]::ASCII)
    Write-Ok "created $CliShim"
    Add-ToUserPath $BinDir

    $commitSha = (Get-Content (Join-Path $CoreDir '.neovarch-source-commit') -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $commitSha -or $commitSha.Length -lt 7) { $commitSha = 'unknown-local' }
    $receipt = [ordered]@{
        schemaVersion = 1
        pinnedCommit  = $commitSha
        pinnedBranch  = $(if ($Branch) { $Branch } else { $null })
        completedAt   = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        installer     = 'scripts/install.ps1'
    }
    [IO.File]::WriteAllText((Join-Path $CoreDir $ReceiptName), ($receipt | ConvertTo-Json))
    $ver = & $exe --version 2>$null | Select-Object -First 1
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'neovarch --version failed' }
    Write-Ok "$ver"
}

function Install-Core {
    Install-Uv
    Install-CoreFiles
    Install-CorePython
    Install-CoreCli
}

function Write-Manifest {
    $m = '{"protocol_version":1,"stages":[{"name":"uv","title":"Alat Python (uv)","category":"tooling","needs_user_input":false},{"name":"core","title":"Inti Neovarch","category":"source","needs_user_input":false},{"name":"python","title":"Lingkungan Python","category":"dependencies","needs_user_input":false},{"name":"cli","title":"Perintah neovarch","category":"launcher","needs_user_input":false},{"name":"9router","title":"9Router (model gratis)","category":"provider","needs_user_input":false}]}'
    [Console]::Out.WriteLine($m)
}

function Invoke-Stage($name) {
    $script:CurStage = $name
    switch ($name) {
        'uv'     { Install-Uv }
        'core'   { Install-CoreFiles }
        'python' { Install-CorePython }
        'cli'    { Install-CoreCli }
        '9router' { Install-9Router }
        default  { Stop-WithError "unknown stage: $name" }
    }
    if ($Json) { [Console]::Out.WriteLine((@{ ok = $true; stage = $name } | ConvertTo-Json -Compress)) }
}

# --------------------------------------------------------------- 9Router ---

$NodeMajor = 22   # Node.js LTS line installed when Node 18+ is missing

function Test-NodeOk($node) {
    try { $v = & $node -p 'process.versions.node.split(".")[0]' 2>$null; return ([int]$v -ge 18) } catch { return $false }
}

function Install-Node {
    $sys = Get-Command node -ErrorAction SilentlyContinue
    $sysNpm = Get-Command npm -ErrorAction SilentlyContinue
    if ($sys -and $sysNpm -and (Test-NodeOk $sys.Source)) { Write-Ok "Node.js $(& $sys.Source -v)"; return $sysNpm.Source }
    $own = Join-Path $ToolsDir 'node\node.exe'
    if ((Test-Path $own) -and (Test-NodeOk $own)) { Write-Ok "Node.js $(& $own -v) ($ToolsDir\node)"; return (Join-Path $ToolsDir 'node\npm.cmd') }
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }
    Write-Step "Installing Node.js $NodeMajor LTS into $ToolsDir\node (needed by 9Router)"
    $base = "https://nodejs.org/dist/latest-v$NodeMajor.x"
    $sums = (Invoke-WebRequest -UseBasicParsing "$base/SHASUMS256.txt").Content
    $line = ($sums -split "`n") | Where-Object { $_ -match "node-v[0-9.]+-win-$arch\.zip$" } | Select-Object -First 1
    if (-not $line) { throw "Node.js zip for win-$arch not found" }
    $want, $file = ($line.Trim() -split '\s+')
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("neovarch-node-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    try {
        Invoke-WebRequest -UseBasicParsing "$base/$file" -OutFile (Join-Path $tmp $file)
        $got = (Get-FileHash (Join-Path $tmp $file) -Algorithm SHA256).Hash.ToLower()
        if ($got -ne $want.ToLower()) { throw 'Node.js checksum mismatch' }
        Expand-Archive (Join-Path $tmp $file) -DestinationPath $tmp -Force
        $dest = Join-Path $ToolsDir 'node'
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        New-Item -ItemType Directory -Path $ToolsDir -Force | Out-Null
        Move-Item (Join-Path $tmp ($file -replace '\.zip$', '')) $dest
    } finally { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    Add-ToUserPath (Join-Path $ToolsDir 'node')
    $env:Path = (Join-Path $ToolsDir 'node') + ';' + $env:Path
    Write-Ok "Node.js $(& $own -v)"
    return (Join-Path $ToolsDir 'node\npm.cmd')
}

function Install-9Router {
    if ($No9Router -or $env:NEOVARCH_NO_9ROUTER) { Write-Host '    9Router skipped'; return }
    $have = Get-Command 9router -ErrorAction SilentlyContinue
    if (-not $have -and (Test-Path (Join-Path $ToolsDir 'node\9router.cmd'))) { $have = $true }
    if ($have) { Write-Ok '9Router already installed' }
    else {
        try { $npm = Install-Node } catch { Write-Warn2 "Node.js not installed ($($_.Exception.Message)). Later: npm install -g 9router"; return }
        Write-Step 'Installing 9Router (npm install -g 9router)'
        & $npm install -g 9router --no-fund --no-audit 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Warn2 'npm install -g 9router failed. Later: npm install -g 9router'; return }
        Write-Ok '9Router installed'
    }
    if (-not (Test-Path $CliShim)) { Write-Warn2 'neovarch command missing; skipping 9Router setup'; return }
    Write-Step 'Starting 9Router and choosing the free default model'
    $env:Path = (Join-Path $ToolsDir 'node') + ';' + (Join-Path $env:APPDATA 'npm') + ';' + $env:Path
    & $CliShim router setup
    if ($LASTEXITCODE -eq 0) { Write-Ok '9Router ready (dashboard: http://localhost:20128/dashboard)' }
    else {
        Write-Warn2 '9Router needs one step in its dashboard: open http://localhost:20128/dashboard'
        Write-Host '      (the desktop app shows a "Buka dashboard 9Router" button for it)'
    }
}

# --------------------------------------------------------------- desktop ---

function New-Shortcut($path, $target, $workdir) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $target
    $lnk.WorkingDirectory = $workdir
    $lnk.IconLocation = "$target,0"
    $lnk.Description = 'Neovarch Agent desktop'
    $lnk.Save()
}

function Stop-RunningApp {
    # Only Neovarch's own desktop ('NeovarchAgent' is the 1.1.x Flutter name). Never Hermes.
    $procs = Get-Process -Name $ProcName, 'NeovarchAgent' -ErrorAction SilentlyContinue
    if ($procs) {
        Write-Step "Closing the running $AppName"
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 1200
    }
}

function Remove-LegacyFlutterApp {
    $legacyExe = Join-Path $PortableDir 'NeovarchAgent.exe'
    if (Test-Path $legacyExe) {
        Remove-Item $PortableDir -Recurse -Force
        Write-Ok 'removed the previous (1.1.x) desktop build'
    }
}

function Get-ReleaseUrl($asset) {
    if ($Version) {
        if ($Version -notmatch '^v') { $script:Version = "v$Version" }
        return @("$ReleasesUrl/download/$script:Version/$asset", $script:Version)
    }
    return @("$ReleasesUrl/latest/download/$asset", 'latest')
}

function Install-Setup($tmp) {
    $url, $label = Get-ReleaseUrl $SetupAsset
    Write-Step "Downloading $AppName installer ($label)"
    Write-Host "    $url" -ForegroundColor DarkGray
    $setup = Join-Path $tmp $SetupAsset
    try { Invoke-WebRequest -Uri $url -OutFile $setup -UseBasicParsing }
    catch { Stop-WithError "download failed ($($_.Exception.Message)). Check the tag or see $ReleasesUrl" }
    Stop-RunningApp
    Remove-LegacyFlutterApp
    Write-Step 'Installing (silent, per user)'
    $p = Start-Process -FilePath $setup -ArgumentList '/S', "/D=$InstallDir" -Wait -PassThru
    if ($p.ExitCode -ne 0) { Stop-WithError "installer exited with code $($p.ExitCode)" }
    $exePath = Join-Path $InstallDir $ExeName
    if (-not (Test-Path $exePath)) { Stop-WithError "installer finished but $exePath is missing" }
    Write-Ok "installed to $InstallDir"
    return $exePath
}

function Install-Portable($tmp) {
    $url, $label = Get-ReleaseUrl $ZipAsset
    Write-Step "Downloading $AppName ($label, portable zip)"
    Write-Host "    $url" -ForegroundColor DarkGray
    $zip = Join-Path $tmp $ZipAsset
    try { Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing }
    catch { Stop-WithError "download failed ($($_.Exception.Message)). Check the tag or see $ReleasesUrl" }
    Write-Step 'Unpacking'
    $unz = Join-Path $tmp 'x'
    Expand-Archive -Path $zip -DestinationPath $unz -Force
    $exe = Get-ChildItem -Path $unz -Filter $ExeName -Recurse | Select-Object -First 1
    if (-not $exe) { Stop-WithError "archive layout unexpected (no $ExeName)" }
    Stop-RunningApp
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    if (Test-Path $PortableDir) { Remove-Item $PortableDir -Recurse -Force }
    Move-Item -Path $exe.DirectoryName -Destination $PortableDir
    Write-Ok "installed to $PortableDir"
    $exePath = Join-Path $PortableDir $ExeName
    try {
        if ($StartMenu)  { New-Shortcut $StartMenu $exePath $PortableDir;  Write-Ok 'added Start Menu shortcut' }
        if ($DesktopLnk) { New-Shortcut $DesktopLnk $exePath $PortableDir; Write-Ok 'added Desktop shortcut' }
    } catch { Write-Warn2 "could not create shortcuts: $($_.Exception.Message)" }
    return $exePath
}

# ------------------------------------------------------------- uninstall ---

function Invoke-Uninstall {
    Write-Banner
    Write-Step "Removing $AppName"
    Stop-RunningApp
    $removed = $false
    if (Test-Path $Uninstaller) {
        $p = Start-Process -FilePath $Uninstaller -ArgumentList '/S' -Wait -PassThru
        if ($p.ExitCode -eq 0) { Write-Ok "ran $Uninstaller"; $removed = $true }
        else { Write-Warn2 "uninstaller exited with code $($p.ExitCode)" }
    }
    foreach ($f in @($StartMenu, $DesktopLnk) | Where-Object { $_ }) {
        if (Test-Path $f) { Remove-Item $f -Force; Write-Ok "removed $f"; $removed = $true }
    }
    Remove-FromUserPath $BinDir
    # 9Router installed under the Neovarch home goes with it (a global npm one stays).
    $ownNode = Join-Path $ToolsDir 'node'
    Get-Process node -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($ownNode, [StringComparison]::OrdinalIgnoreCase) } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Remove-FromUserPath $ownNode
    if (Test-Path $Root) { Remove-Item $Root -Recurse -Force; Write-Ok "removed $Root"; $removed = $true }
    if (Test-Path $NeovarchHome) {
        Assert-NotHermes $NeovarchHome
        if ($NeovarchHome -ieq $HOME -or $NeovarchHome -ieq $LocalAppData) { Stop-WithError "refusing to remove $NeovarchHome" }
        Remove-Item $NeovarchHome -Recurse -Force; Write-Ok "removed $NeovarchHome"; $removed = $true
    }
    Write-Host ''
    if ($removed) { Write-Host "$AppName uninstalled. A Hermes Agent install, if any, was not touched." }
    else { Write-Host "$AppName is not installed." }
}

# ------------------------------------------------------------------ main ---

function Invoke-Install {
    Write-Banner
    $arch = $env:PROCESSOR_ARCHITECTURE
    if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }
    if ($arch -eq 'x86') { Write-Host "$AppName for 32-bit Windows is not available. See $ReleasesUrl/latest"; return }

    Install-Core
    Install-9Router

    if (-not $CoreOnly) {
        if ($arch -eq 'ARM64') { Write-Warn2 'No native ARM64 desktop build yet; installing the x64 build (runs under emulation).' }
        $tmp = Join-Path ([IO.Path]::GetTempPath()) ("neovarch-" + [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tmp -Force | Out-Null
        try {
            if ($Portable) { [void](Install-Portable $tmp) } else { [void](Install-Setup $tmp) }
        } finally {
            Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Host ''
    Write-Host "$AppName is installed. Data: $NeovarchHome"
    Write-Host '  neovarch            ' -ForegroundColor Red -NoNewline; Write-Host 'chat in the terminal (free model via 9Router; open a new terminal first)'
    Write-Host '  neovarch router     ' -ForegroundColor Red -NoNewline; Write-Host '9Router status (dashboard: http://localhost:20128/dashboard)'
    if (-not $CoreOnly) { Write-Host '  neovarch desktop    ' -ForegroundColor Red -NoNewline; Write-Host 'open the desktop app (or use the Start Menu)' }
}

if ($Manifest) { Write-Manifest; return }
if ($Stage) { Invoke-Stage $Stage; return }
if ($Uninstall -or $env:NEOVARCH_UNINSTALL -eq '1') { Invoke-Uninstall } else { Invoke-Install }
