[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ArchivePath,

    [ValidateSet("parallel", "sequential")]
    [string]$ExecutionMode = "parallel"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$expectedArchiveSha256 = "478010791a6f9781f96bc5d3b4f20cbdb62d8ea5ea211a76b5f4cbb3f1958ccf"

$expectedInputs = @(
    [pscustomobject]@{ Name = "GL_HAZTBLT_M5_B2_2013.TMP"; Sha256 = "a8b6f73b8ae2a7f98868972d8b49e05055e4d1efe8f8264385ec0b07128663bf" },
    [pscustomobject]@{ Name = "PB2002_tectonic_zones.grd"; Sha256 = "4b2fbb6eeee415453caadb3463531b6ebf3a8716e5215073041381d3f49a7d7d" },
    [pscustomobject]@{ Name = "underwater.grd"; Sha256 = "15f1c5b74aa66b1911681097ca498d885d31a053287707a3efd2a14efee9ba4b" },
    [pscustomobject]@{ Name = "PB2002_steps.dat"; Sha256 = "bb3f7222787448c6aed731ef15791d1b88be9c1c520cad31fa35e7a81a049180" },
    [pscustomobject]@{ Name = "GSRM_average_strain_v2.1.txt"; Sha256 = "26cb5f6fd5faca7050375e5cac8396a9713585031206d8ba221575feae33b42b" },
    [pscustomobject]@{ Name = "GCMT_shallow_5p767_1977-2013.eqc"; Sha256 = "c85c9e2acd6c02dee85e0814bdb1d88f1fce598fc1b61e52448f3b1f299177f9" }
)

if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
    throw "Archive not found: $ArchivePath"
}
$ArchivePath = (Resolve-Path -LiteralPath $ArchivePath).Path

$archiveHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($archiveHash -ne $expectedArchiveSha256) {
    throw "Archive SHA-256 mismatch. Expected $expectedArchiveSha256; got $archiveHash. Do not continue."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$gear1Root = Join-Path $repoRoot "data\external\gear1"
$sourceDir = Join-Path $gear1Root "source"
$runDir = Join-Path $gear1Root "run"
$smoothedDir = Join-Path $gear1Root "expanded_smoothed"
$underwaterDir = Join-Path $gear1Root "expanded_underwater"
$gsrmDir = Join-Path $gear1Root "expanded_gsrm"

New-Item -ItemType Directory -Path $gear1Root, $runDir -Force | Out-Null

Write-Host "Archive checksum verified."
Write-Host "Extracting the Dryad archive..."
Expand-Archive -LiteralPath $ArchivePath -DestinationPath $sourceDir -Force

$gear1Source = Join-Path $sourceDir "GEAR1_forecast"
$pbSource = Join-Path $sourceDir "PB2002"
$shiftSource = Join-Path $sourceDir "SHIFT_GSRM2_forecast"
$kaganSource = Join-Path $sourceDir "Kagan_2009_GJI_I_scores"

$smoothedZip = Join-Path $gear1Source "GL_HAZTBLT_M5_B2_2013.zip"
$underwaterZip = Join-Path $kaganSource "underwater.grd.zip"
$gsrmCompressed = Join-Path $shiftSource "GSRM_average_strain_v2.1.txt.Z"

foreach ($requiredPath in @($smoothedZip, $underwaterZip, $gsrmCompressed)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required source file is missing from the extracted archive: $requiredPath"
    }
}

Write-Host "Expanding the two nested ZIP input files..."
Expand-Archive -LiteralPath $smoothedZip -DestinationPath $smoothedDir -Force
Expand-Archive -LiteralPath $underwaterZip -DestinationPath $underwaterDir -Force

$smoothedFile = Get-ChildItem -LiteralPath $smoothedDir -Recurse -File |
    Where-Object { $_.Name -eq "GL_HAZTBLT_M5_B2_2013.TMP" } |
    Select-Object -First 1
$underwaterFile = Get-ChildItem -LiteralPath $underwaterDir -Recurse -File |
    Where-Object { $_.Name -eq "underwater.grd" } |
    Select-Object -First 1

if (-not $smoothedFile) { throw "Nested archive did not contain GL_HAZTBLT_M5_B2_2013.TMP." }
if (-not $underwaterFile) { throw "Nested archive did not contain underwater.grd." }

$sevenZip = Get-Command "7z.exe" -ErrorAction SilentlyContinue
if (-not $sevenZip) { $sevenZip = Get-Command "7z" -ErrorAction SilentlyContinue }

$sevenZipPath = $null
if ($sevenZip) {
    $sevenZipPath = $sevenZip.Source
} else {
    $candidates = @(
        (Join-Path $env:ProgramFiles "7-Zip\7z.exe"),
        (Join-Path ([Environment]::GetFolderPath("ProgramFilesX86")) "7-Zip\7z.exe")
    )
    $sevenZipPath = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
}
if (-not $sevenZipPath) {
    throw "7-Zip was not found. Install 7-Zip, then run this script again; it is needed to decompress the Unix .Z GSRM file."
}

if (Test-Path -LiteralPath $gsrmDir) {
    Remove-Item -LiteralPath $gsrmDir -Recurse -Force
}
New-Item -ItemType Directory -Path $gsrmDir -Force | Out-Null
Write-Host "Decompressing the Unix .Z GSRM file with 7-Zip..."
& $sevenZipPath x -y "-o$gsrmDir" $gsrmCompressed | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "7-Zip failed to decompress the GSRM .Z file (exit code $LASTEXITCODE)."
}
$gsrmFile = Get-ChildItem -LiteralPath $gsrmDir -Recurse -File |
    Where-Object { $_.Name -eq "GSRM_average_strain_v2.1.txt" } |
    Select-Object -First 1
if (-not $gsrmFile) { throw "The GSRM .Z archive did not produce GSRM_average_strain_v2.1.txt." }

$sourceMap = @{
    "GL_HAZTBLT_M5_B2_2013.TMP" = $smoothedFile.FullName
    "PB2002_tectonic_zones.grd" = (Join-Path $pbSource "PB2002_tectonic_zones.grd.txt")
    "underwater.grd" = $underwaterFile.FullName
    "PB2002_steps.dat" = (Join-Path $pbSource "PB2002_steps.dat.txt")
    "GSRM_average_strain_v2.1.txt" = $gsrmFile.FullName
    "GCMT_shallow_5p767_1977-2013.eqc" = (Join-Path $shiftSource "GCMT_shallow_5p767_1977-2013.eqc.txt")
}

$manifestLines = @()
foreach ($item in $expectedInputs) {
    $sourcePath = $sourceMap[$item.Name]
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Input source file is missing: $sourcePath"
    }
    $actualHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $item.Sha256) {
        throw "SHA-256 mismatch for $($item.Name). Expected $($item.Sha256); got $actualHash."
    }
    Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $runDir $item.Name) -Force
    $manifestLines += "$actualHash  $($item.Name)"
    Write-Host "Verified: $($item.Name)"
}

$parametersSource = Join-Path $gear1Source "GEAR1_parameters.dat.txt"
if (-not (Test-Path -LiteralPath $parametersSource -PathType Leaf)) {
    throw "GEAR1_parameters.dat.txt is missing."
}
Copy-Item -LiteralPath $parametersSource -Destination (Join-Path $runDir "GEAR1_parameters.dat") -Force
$manifestLines | Set-Content -LiteralPath (Join-Path $runDir "INPUT_SHA256SUMS.txt") -Encoding ASCII

if ($ExecutionMode -eq "parallel") {
    $selectedExe = Join-Path $gear1Source "GEAR1_for_CSEP-Win64par.exe"
    $selectedExeName = "GEAR1_for_CSEP-Win64par.exe"
    $dllSource = Join-Path $sourceDir "REQUIRED_DLL_files\Win64_version\libiomp5md.dll"
    if (-not (Test-Path -LiteralPath $dllSource -PathType Leaf)) {
        throw "The required 64-bit Intel OpenMP DLL is missing from the archive."
    }
    Copy-Item -LiteralPath $dllSource -Destination (Join-Path $runDir "libiomp5md.dll") -Force
} else {
    $selectedExe = Join-Path $gear1Source "GEAR1_for_CSEP-Win64seq.exe"
    $selectedExeName = "GEAR1_for_CSEP-Win64seq.exe"
}
if (-not (Test-Path -LiteralPath $selectedExe -PathType Leaf)) {
    throw "Selected original GEAR1 executable is missing: $selectedExe"
}
Copy-Item -LiteralPath $selectedExe -Destination (Join-Path $runDir $selectedExeName) -Force
Copy-Item -LiteralPath (Join-Path $gear1Source "how_to_build_the_GEAR1_XML_file.txt") -Destination $runDir -Force

Write-Host ""
Write-Host "GEAR1 input directory prepared and all six inputs passed SHA-256 verification:"
Write-Host "  $runDir"
Write-Host ""
Write-Host "No forecast has been started. To run the author's original Windows executable:"
Write-Host "  Set-Location -LiteralPath '$runDir'"
Write-Host "  .\$selectedExeName GEAR1_parameters.dat"
Write-Host ""
Write-Host "Before running, ensure the computer will not sleep and has sufficient free disk space."
Write-Host "The author's instructions estimate about 5-6 GB RAM and a multi-hour to multi-day run."
