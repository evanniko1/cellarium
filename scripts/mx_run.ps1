# ROUTE1 step-2 test matrix runner: 3 arms x 3 seeds x N generations, real full generations.
#
# Each (arm, seed) is one detached container running runSim.py with --generations N. Generations are
# sequential inside a chain (a daughter needs its mother's inherited state), so the parallelism is
# across the 9 chains only. Concurrency is capped because the box has ~18.8 GB of Docker memory and
# each sim holds the sim_data pickle resident.
#
# Every container's stdout goes to its own log file, and the exit code is captured DIRECTLY from
# `docker wait` -- never inferred from the log text.

param(
    [int]$Generations = 3,
    [int]$MaxParallel = 5,
    [string]$Image = "wcecoli-sim:route1matrix",
    [string]$LogDir = "C:/Users/vmnik/AppData/Local/Temp/claude/C--dev-wcEcoli/d8db455b-1cb1-42c8-8c2b-82485b2eb2c2/scratchpad/mxlogs",
    [string]$Prefix = "mx"
)

$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$arms = @(
    @{ tag = "fam"; res = "family";      split = "abundance" },
    @{ tag = "abu"; res = "isoacceptor"; split = "abundance" },
    @{ tag = "equ"; res = "isoacceptor"; split = "equal" }
)
$seeds = @(0, 1, 2)

$cells = @()
foreach ($a in $arms) { foreach ($s in $seeds) {
    $cells += @{ name = "$Prefix`_$($a.tag)_s$s"; res = $a.res; split = $a.split; seed = $s; tag = $a.tag }
} }

$running = @{}    # container name -> cell
$queue = [System.Collections.ArrayList]@($cells)
$results = @()

function Start-Cell($c) {
    $cname = "mxrun_$($c.name)"
    & docker rm -f $cname 2>$null | Out-Null
    $dargs = @(
        "run", "-d", "--name", $cname,
        "-v", "C:/dev/wcEcoli/out:/wcEcoli/out",
        "-e", "PYTHONPATH=/wcEcoli", "-w", "/wcEcoli",
        "--entrypoint", "python", $Image,
        "/wcEcoli/runscripts/manual/runSim.py", $c.name,
        "--trna-charging",
        "--trna-charging-resolution", $c.res,
        "--trna-demand-split", $c.split,
        "--generations", "$Generations",
        "--seed", "$($c.seed)"
    )
    $id = (& docker $dargs) | Select-Object -Last 1
    Write-Host ("{0}  LAUNCH {1} res={2} split={3} seed={4} container={5}" -f (Get-Date -Format "HH:mm:ss"), $c.name, $c.res, $c.split, $c.seed, $cname)
    return $cname
}

while ($queue.Count -gt 0 -or $running.Count -gt 0) {
    while ($running.Count -lt $MaxParallel -and $queue.Count -gt 0) {
        $c = $queue[0]; $queue.RemoveAt(0)
        $cname = Start-Cell $c
        $running[$cname] = $c
        Start-Sleep -Seconds 15   # stagger the sim_data pickle loads
    }

    Start-Sleep -Seconds 30
    $alive = (& docker ps --format "{{.Names}}") -split "`n" | ForEach-Object { $_.Trim() }
    foreach ($cname in @($running.Keys)) {
        if ($alive -notcontains $cname) {
            $c = $running[$cname]
            $code = (& docker wait $cname) | Select-Object -Last 1
            & docker logs $cname 2>&1 | Out-File -FilePath (Join-Path $LogDir "$($c.name).log") -Encoding utf8
            & docker rm -f $cname 2>$null | Out-Null
            Write-Host ("{0}  DONE   {1} exit={2}" -f (Get-Date -Format "HH:mm:ss"), $c.name, $code)
            $results += [pscustomobject]@{ name = $c.name; exit = [int]$code }
            $running.Remove($cname)
        }
    }
}

Write-Host "==== MATRIX EXIT CODES ===="
$results | ForEach-Object { Write-Host ("{0} exit={1}" -f $_.name, $_.exit) }
$bad = ($results | Where-Object { $_.exit -ne 0 }).Count
Write-Host "MATRIX_NONZERO_EXITS=$bad"
