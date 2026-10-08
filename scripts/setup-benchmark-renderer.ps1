$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$deps = Join-Path $repoRoot 'backend\.deps'
$target = Join-Path $deps 'fluidsynth-2.5.6'
if (Test-Path -LiteralPath (Join-Path $target 'bin\fluidsynth.exe')) {
    Write-Host 'Portable renderer already present. Fixture manifest records its version/hash.'
    return
}
New-Item -ItemType Directory -Force $deps | Out-Null
$zip = Join-Path $deps 'fluidsynth-2.5.6.zip'
Invoke-WebRequest 'https://github.com/FluidSynth/fluidsynth/releases/download/v2.5.6/fluidsynth-v2.5.6-win10-x64-cpp11.zip' -OutFile $zip
if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne 'A4B8BD4F133B7B6770537F6C18B2B2B93579338D51E26F777D025E40E15A7E81') {
    throw 'Official FluidSynth asset checksum mismatch.'
}
$package = Join-Path $deps 'fluidsynth-2.5.6-package'
Expand-Archive -LiteralPath $zip -DestinationPath $package
Copy-Item -LiteralPath (Join-Path $package 'fluidsynth-v2.5.6-win10-x64-cpp11') -Destination $target -Recurse
Write-Host 'Portable FluidSynth ready; no system installation or PATH change.'
