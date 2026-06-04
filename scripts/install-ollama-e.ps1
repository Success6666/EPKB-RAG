param(
    [string]$InstallDir = "E:\Ollama",
    [string]$ModelsDir = "E:\Ollama\models",
    [ValidateSet("installer", "portable")]
    [string]$Mode = "installer",
    [string]$LocalPackage = ""
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path $InstallDir, $ModelsDir | Out-Null
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $ModelsDir, "User")
$env:OLLAMA_MODELS = $ModelsDir

function Find-OllamaExe {
    $candidates = @(
        (Join-Path $InstallDir "ollama.exe"),
        (Join-Path $InstallDir "portable\ollama.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    return $null
}

if ($LocalPackage) {
    if (-not (Test-Path $LocalPackage)) {
        throw "Local package not found: $LocalPackage"
    }

    if ($LocalPackage.EndsWith(".zip")) {
        $portableDir = Join-Path $InstallDir "portable"
        New-Item -ItemType Directory -Force -Path $portableDir | Out-Null
        Expand-Archive -Path $LocalPackage -DestinationPath $portableDir -Force
    }
    else {
        Start-Process -FilePath $LocalPackage -ArgumentList @("/VERYSILENT", "/NORESTART", "/DIR=`"$InstallDir`"") -Wait -WindowStyle Hidden
    }
}
elseif ($Mode -eq "portable") {
    winget install --id Ollama.Ollama.Portable --exact --source winget --location (Join-Path $InstallDir "portable") --accept-package-agreements --accept-source-agreements --disable-interactivity
}
else {
    winget install --id Ollama.Ollama --exact --source winget --silent --location $InstallDir --accept-package-agreements --accept-source-agreements --disable-interactivity
}

$ollama = Find-OllamaExe
if (-not $ollama) {
    throw "ollama.exe was not found. Retry later or pass -LocalPackage with OllamaSetup.exe or ollama-windows-amd64.zip."
}

& $ollama --version
Write-Host "OLLAMA_EXE=$ollama"
Write-Host "OLLAMA_MODELS=$ModelsDir"
Write-Host "Start server: & `"$ollama`" serve"
Write-Host "Pull model:   & `"$ollama`" pull qwen2.5:14b"
Write-Host "Pull embed:   & `"$ollama`" pull bge-m3"
