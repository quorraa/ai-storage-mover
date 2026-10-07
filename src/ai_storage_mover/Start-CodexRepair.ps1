param([Parameter(Mandatory)][string]$Record,
      [Parameter(Mandatory)][string]$Worker,
      [Parameter(Mandatory)][string]$TaskName,
      [string]$SourceRoot)
$ErrorActionPreference='Stop'
$Record=[IO.Path]::GetFullPath($Record)
$Worker=[IO.Path]::GetFullPath($Worker)
if(-not (Test-Path -LiteralPath $Worker -PathType Leaf)){throw 'Repair worker executable is missing'}
if($TaskName -cne ('AIStorageMover-Repair-'+[IO.Path]::GetFileName($Record)) -or [IO.Path]::GetFileName($Record) -cnotmatch '^[a-f0-9]{32}$'){throw 'Invalid repair task identity'}
if(Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue){throw 'Repair task already exists'}
function Quote-Literal([string]$value){return "'"+$value.Replace("'","''")+"'"}
$launcher=Join-Path $Record 'Run-Repair.ps1'
$body="`$ErrorActionPreference='Stop'`r`n"
$body+='$repairRecord='+ (Quote-Literal $Record)+"`r`n"
$body+='$repairTask='+ (Quote-Literal $TaskName)+"`r`ntry {`r`n"
if($SourceRoot){$body+='$env:PYTHONPATH='+ (Quote-Literal $SourceRoot)+"`r`n"}
$body+='& '+(Quote-Literal $Worker)
if($SourceRoot){$body+=' -m ai_storage_mover'}
$body+=' repair-worker --record '+(Quote-Literal $Record)+' *> '+(Quote-Literal (Join-Path $Record 'worker.log'))+"`r`n"
$body+=@'
if($LASTEXITCODE -ne 0){throw ('Repair worker exited with code '+$LASTEXITCODE)}
}catch{
    $failure=$_.Exception.Message
    $status=Join-Path $repairRecord 'status.json'
    $current=Get-Content -LiteralPath $status -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
    if($current.phase -notin @('complete','not-needed','failed','cancelled','blocked')){
        @{phase='failed';detail=('Repair worker stopped: '+$failure+'. Inspect the retained record.');updated=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()} | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
    }
}finally{
    if(Get-ScheduledTask -TaskName $repairTask -ErrorAction SilentlyContinue){
        try{Unregister-ScheduledTask -TaskName $repairTask -Confirm:$false -ErrorAction Stop}
        catch{('Remove inactive task '+$repairTask) | Set-Content -LiteralPath (Join-Path $repairRecord 'task-cleanup-warning.txt')}
    }
}
'@
[IO.File]::WriteAllText($launcher,$body,[Text.UTF8Encoding]::new($true))
$powerShell=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action=New-ScheduledTaskAction -Execute $powerShell -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$launcher+'"') -WorkingDirectory $Record
$user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
try{
    Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $principal -Settings $settings | Out-Null
    Start-ScheduledTask -TaskName $TaskName
}catch{
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    throw
}
