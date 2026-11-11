[CmdletBinding()]
param(
    [ValidateSet("parallel", "sequential")]
    [string]$ExecutionMode = "parallel"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$expectedInputs = @(
    [pscustomobject]@{ Name = "GL_HAZTBLT_M5_B2_2013.TMP"; Sha256 = "a8b6f73b8ae2a7f98868972d8b49e05055e4d1efe8f8264385ec0b07128663bf" },
    [pscustomobject]@{ Name = "PB2002_tectonic_zones.grd"; Sha256 = "4b2fbb6eeee415453caadb3463531b6ebf3a8716e5215073041381d3f49a7d7d" },
    [pscustomobject]@{ Name = "underwater.grd"; Sha256 = "15f1c5b74aa66b1911681097ca498d885d31a053287707a3efd2a14efee9ba4b" },
    [pscustomobject]@{ Name = "PB2002_steps.dat"; Sha256 = "bb3f7222787448c6aed731ef15791d1b88be9c1c520cad31fa35e7a81a049180" },
    [pscustomobject]@{ Name = "GSRM_average_strain_v2.1.txt"; Sha256 = "26cb5f6fd5faca7050375e5cac8396a9713585031206d8ba221575feae33b42b" },
    [pscustomobject]@{ Name = "GCMT_shallow_5p767_1977-2013.eqc"; Sha256 = "c85c9e2acd6c02dee85e0814bdb1d88f1fce598fc1b61e52448f3b1f299177f9" }
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $repoRoot "data\external\gear1\run"
$parameterFile = Join-Path $runDir "GEAR1_parameters.dat"

if (-not (Test-Path -LiteralPath $parameterFile -PathType Leaf)) {
    throw "GEAR1 is not prepared. Run research\prepare_gear1_windows.ps1 first."
}

if ($ExecutionMode -eq "parallel") {
    $exeName = "GEAR1_for_CSEP-Win64par.exe"
} else {
    $exeName = "GEAR1_for_CSEP-Win64seq.exe"
}
$exePath = Join-Path $runDir $exeName
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "The selected executable is missing: $exePath. Re-run the preparation script with -ExecutionMode $ExecutionMode."
}
if ($ExecutionMode -eq "parallel" -and -not (Test-Path -LiteralPath (Join-Path $runDir "libiomp5md.dll") -PathType Leaf)) {
    throw "libiomp5md.dll is missing from the run directory."
}

Write-Host "Checking the six input files..."
foreach ($item in $expectedInputs) {
    $path = Join-Path $runDir $item.Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required input file is missing: $path"
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $item.Sha256) {
        throw "SHA-256 mismatch for $($item.Name). Expected $($item.Sha256); got $actual."
    }
    Write-Host "  OK $($item.Name)"
}

$parameterLines = Get-Content -LiteralPath $parameterFile
if ($parameterLines.Count -lt 11) {
    throw "GEAR1_parameters.dat is unexpectedly short."
}
$expectedNames = @(
    "smoothedSeismicityDatPath=GL_HAZTBLT_M5_B2_2013.TMP",
    "tectonicZonesDatPath=PB2002_tectonic_zones.grd",
    "underwaterDatPath=underwater.grd",
    "plateBoundariesDatPath=PB2002_steps.dat",
    "averageStrainDatPath=GSRM_average_strain_v2.1.txt",
    "calibrationCatalogDatPath=GCMT_shallow_5p767_1977-2013.eqc"
)
for ($i = 0; $i -lt $expectedNames.Count; $i++) {
    if ($parameterLines[$i].Trim() -ne $expectedNames[$i]) {
        throw "Parameter file line $($i + 1) differs from the expected original GEAR1 input path."
    }
}

$outputLine = $parameterLines | Where-Object { $_ -like "forecastXmlPath=*" } | Select-Object -First 1
if (-not $outputLine) { throw "forecastXmlPath is missing from GEAR1_parameters.dat." }
$outputName = $outputLine.Substring("forecastXmlPath=".Length).Trim()
if ([System.IO.Path]::IsPathRooted($outputName)) {
    $outputPath = $outputName
} else {
    $outputPath = Join-Path $runDir $outputName
}
if (Test-Path -LiteralPath $outputPath) {
    throw "Output already exists; refusing to overwrite it: $outputPath"
}

$os = Get-CimInstance -ClassName Win32_OperatingSystem
$totalRamGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
$freeRamGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$driveRoot = [System.IO.Path]::GetPathRoot($runDir)
$drive = [System.IO.DriveInfo]::new($driveRoot)
$freeDiskGB = [math]::Round($drive.AvailableFreeSpace / 1GB, 2)

Write-Host ""
Write-Host "GEAR1 preflight:"
Write-Host "  Mode:                $ExecutionMode"
Write-Host "  Total visible RAM:   $totalRamGB GB"
Write-Host "  Free RAM now:        $freeRamGB GB"
Write-Host "  Free disk space:     $freeDiskGB GB"
Write-Host "  Output:              $outputPath"

if ($totalRamGB -lt 5.0) {
    throw "The author recommends 5-6 GB total RAM. This computer reports less than 5 GB; refusing to launch."
}
if ($totalRamGB -lt 6.0) {
    Write-Warning "The author recommends 5-6 GB total RAM. This machine is below 6 GB; close other applications before proceeding."
}
if ($freeDiskGB -lt 6.0) {
    throw "Less than 6 GB of free disk space is available. The author estimates an XML output around 3.8 GB."
}
if ($freeRamGB -lt 4.0) {
    Write-Warning "Less than 4 GB RAM is currently free. Close other applications before proceeding."
}

Write-Host ""
Write-Warning "This is the original 2014 GEAR1 forecast configuration: 2014-01-01 through 2015-01-01. It is a static long-term forecast, not a current short-term forecast."
Write-Warning "The run may take several hours. Keep the computer awake and do not close this PowerShell window."
Write-Host "Type RUN to start the original executable. Any other input cancels without changing the data."
$confirmation = Read-Host "Start GEAR1"
if ($confirmation -cne "RUN") {
    Write-Host "Cancelled. No forecast was started."
    exit 0
}

$consoleOut = Join-Path $runDir "GEAR1_console_stdout.txt"
$consoleErr = Join-Path $runDir "GEAR1_console_stderr.txt"
$programLog = Join-Path $runDir "GEAR1_for_CSEP_log.txt"
foreach ($oldLog in @($consoleOut, $consoleErr, $programLog)) {
    if (Test-Path -LiteralPath $oldLog) {
        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        Move-Item -LiteralPath $oldLog -Destination "$oldLog.$stamp.bak"
    }
}

Write-Host "Starting $exeName ..."
$startArgs = @{
    FilePath = $exePath
    ArgumentList = "GEAR1_parameters.dat"
    WorkingDirectory = $runDir
    RedirectStandardOutput = $consoleOut
    RedirectStandardError = $consoleErr
    Wait = $true
    PassThru = $true
}
$process = Start-Process @startArgs

Write-Host "Process exit code: $($process.ExitCode)"
if ($process.ExitCode -ne 0) {
    throw "GEAR1 ended with non-zero exit code $($process.ExitCode). Inspect $consoleErr and $programLog."
}
if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
    throw "The process returned exit code 0 but the forecast XML was not created."
}
if (-not (Test-Path -LiteralPath $programLog -PathType Leaf)) {
    throw "GEAR1 log file was not created; completion cannot be verified."
}
$logText = Get-Content -LiteralPath $programLog -Raw
if ($logText -notmatch "STEP #5 completed\.") {
    throw "The log does not contain the STEP #5 completion marker. Do not treat the XML as validated."
}
$outputInfo = Get-Item -LiteralPath $outputPath
Write-Host ""
Write-Host "GEAR1 reached STEP #5 completion."
Write-Host "XML path: $($outputInfo.FullName)"
Write-Host "XML size: $([math]::Round($outputInfo.Length / 1GB, 3)) GB"
Write-Host "Program log: $programLog"
Write-Host "Console output: $consoleOut"
