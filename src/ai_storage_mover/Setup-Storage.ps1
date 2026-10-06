[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PlanPath,
      [Parameter(Mandatory=$true)][string]$StorageRoot,
      [string]$ProjectsPath,
      [string]$PythonPath='python.exe',
      [switch]$ConfigureOnly,
      [switch]$AppsClosed)
$ErrorActionPreference='Stop'
$PlanPath=[IO.Path]::GetFullPath($PlanPath)
$StorageRoot=[IO.Path]::GetFullPath($StorageRoot)
if(-not $ProjectsPath){$ProjectsPath=Join-Path $StorageRoot 'Projects'}
$ProjectsPath=[IO.Path]::GetFullPath($ProjectsPath)
$plan=Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
function Invoke-Mover([string[]]$Arguments){
    & $PythonPath -m ai_storage_mover @Arguments
    if($LASTEXITCODE -ne 0){throw ('Storage operation failed: '+$Arguments[0]+'. Original evidence was retained.')}
}
Invoke-Mover @('inspect','--plan',$PlanPath) | Out-Null
if(-not $AppsClosed){throw 'Quit AI apps and terminals writing to the chosen folders, then rerun with --apps-closed. No processes are terminated.'}
$packages=@(Get-AppxPackage | Where-Object {$_.Name -in @('Claude','OpenAI.Codex')})
$writers=@(Get-CimInstance Win32_Process | Where-Object {
    $process=$_
    $process.Name -in @('codex.exe','claude.exe') -or @($packages | Where-Object {$process.ExecutablePath -and $process.ExecutablePath.StartsWith($_.InstallLocation+'\',[StringComparison]::OrdinalIgnoreCase)}).Count
})
if($writers.Count){throw ('AI apps are still running (process IDs '+(($writers.ProcessId | Sort-Object -Unique)-join ', ')+'). Quit them normally before setup; no files were scanned.')}
$run=[IO.Path]::GetFullPath([string]$plan.run_dir)
New-Item -ItemType Directory -Path $run -Force | Out-Null
function Save-Phase([string]$phase,[int]$percent,[string]$detail){
    $statePath=Join-Path $run 'state.json'
    if(Test-Path -LiteralPath $statePath){
        $state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $percent=[Math]::Max($percent,[int]$state.percent)
        $state.percent=$percent
        [IO.File]::WriteAllText($statePath,($state | ConvertTo-Json -Depth 30))
    }
    $value=@{phase=$phase;percent=$percent;detail=$detail;done=0;total=$null;updated_utc=[DateTime]::UtcNow.ToString('o')}
    $target=Join-Path $run 'status.json'
    $temp=Join-Path $run ('setup-status-'+[Guid]::NewGuid().ToString('N')+'.tmp')
    [IO.File]::WriteAllText($temp,($value | ConvertTo-Json))
    if(Test-Path -LiteralPath $target){[IO.File]::Replace($temp,$target,[NullString]::Value)}else{[IO.File]::Move($temp,$target)}
    Write-Host $detail
}
try{
    # One apply handles final sync and resumable cutover. ConfigureOnly never enumerates project files.
    if(-not $ConfigureOnly){Invoke-Mover @('apply','--plan',$PlanPath,'--apps-closed')}
    Save-Phase 'configuration' 91 'Configuring future writes and saved project paths.'
    $launchers=Join-Path $StorageRoot 'Launchers'
    New-Item -ItemType Directory -Path $launchers -Force | Out-Null
    $runtimePath=Join-Path $launchers 'ai-runtime.local.json'
    Invoke-Mover @('runtime','--storage-root',$StorageRoot,'--output',$runtimePath) | Out-Null
    $runtime=Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
    # Respect destinations selected in the plan rather than assuming profile names.
    foreach($profile in @(@{Source='.codex';Variable='CODEX_HOME'},@{Source='.claude';Variable='CLAUDE_CONFIG_DIR'})){
        $entry=$plan.roots | Where-Object {[IO.Path]::GetFileName([string]$_.source) -eq $profile.Source} | Select-Object -First 1
        if($entry){$runtime.environment.($profile.Variable)=[string]$entry.destination}
        else{
            $current=[Environment]::GetEnvironmentVariable($profile.Variable,'User')
            if($current -and $current.StartsWith($StorageRoot+'\',[StringComparison]::OrdinalIgnoreCase)){$runtime.environment.($profile.Variable)=$current}
            else{$runtime.environment.PSObject.Properties.Remove($profile.Variable)}
        }
    }
    $runtime | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $runtimePath -Encoding UTF8
    $envBackup=@{}
    foreach($property in $runtime.environment.PSObject.Properties){
        New-Item -ItemType Directory -Path $property.Value -Force | Out-Null
        [Environment]::SetEnvironmentVariable($property.Name,$property.Value,'Process')
        # Keep ordinary Windows TEMP unchanged; AI launchers and provider/MCP configs set it explicitly.
        if($property.Name -notin @('TEMP','TMP','TMPDIR')){
            $envBackup[$property.Name]=[Environment]::GetEnvironmentVariable($property.Name,'User')
        }
    }
    $envBackup['Path']=[Environment]::GetEnvironmentVariable('Path','User')
    $envBackup | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run ('user-environment-before-'+[Guid]::NewGuid().ToString('N')+'.json')) -Encoding UTF8
    foreach($property in $runtime.environment.PSObject.Properties){
        if($property.Name -notin @('TEMP','TMP','TMPDIR')){[Environment]::SetEnvironmentVariable($property.Name,$property.Value,'User')}
    }
    $desktops=@()
    foreach($package in $packages | Where-Object Name -eq 'Claude'){
        $folder=Join-Path $env:LOCALAPPDATA ('Packages\'+$package.PackageFamilyName+'\LocalCache\Roaming\Claude')
        if(Test-Path -LiteralPath $folder){$desktops+=$folder}
    }
    $portable=Join-Path $env:APPDATA 'Claude'
    if(Test-Path -LiteralPath (Join-Path $portable 'claude_desktop_config.json')){$desktops+=$portable}
    $configure=@('configure','--plan',$PlanPath,'--runtime',$runtimePath,'--projects',$ProjectsPath,'--apps-closed')
    if($runtime.environment.CODEX_HOME){$configure+=@('--codex-home',[string]$runtime.environment.CODEX_HOME)}
    if($runtime.environment.CLAUDE_CONFIG_DIR){$configure+=@('--claude-home',[string]$runtime.environment.CLAUDE_CONFIG_DIR)}
    foreach($desktop in $desktops){$configure+=@('--claude-desktop-home',$desktop)}
    Invoke-Mover $configure | Set-Content -LiteralPath (Join-Path $run 'provider-setup.json') -Encoding UTF8
    $stores=@($desktops | ForEach-Object {Join-Path $_ 'Local Storage\leveldb'} | Where-Object {Test-Path -LiteralPath $_})
    if($stores.Count){
        Save-Phase 'browser-state' 93 'Repairing closed Claude workspace selectors and file views offline.'
        $node=(Get-Command node.exe -ErrorAction Stop).Source
        $npm=(Get-Command npm.cmd -ErrorAction Stop).Source
        $dependency=Join-Path $StorageRoot 'Toolchains\ai-storage-mover-browser'
        $env:AI_STORAGE_MOVER_LEVEL_MODULE=Join-Path $dependency 'node_modules\classic-level'
        if(-not(Test-Path -LiteralPath $env:AI_STORAGE_MOVER_LEVEL_MODULE)){
            & $npm install --prefix $dependency --ignore-scripts --no-audit --no-fund classic-level@3.0.0
            if($LASTEXITCODE -ne 0){throw 'Optional browser-state dependency could not install. Rerun --configure-only once Node/npm can install it.'}
        }
        foreach($store in $stores){
            & $node (Join-Path $PSScriptRoot 'repair_claude_browser_state.cjs') $PlanPath $store
            if($LASTEXITCODE -ne 0){throw 'Claude workspace cache could not be verified. Its backup is retained; rerun --configure-only after resolving the reported issue.'}
        }
    }
    Save-Phase 'launchers' 95 'Updating AI launchers, shortcuts and selected Explorer pins.'
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Activate-Package.ps1') -Destination $launchers -Force
    $terminal=Join-Path $launchers 'Open-AITerminal.ps1'
    @'
param([Parameter(Mandatory=$true)][string]$RuntimePath,[Parameter(Mandatory=$true)][string]$ProjectPath)
$runtime=Get-Content -LiteralPath $RuntimePath -Raw | ConvertFrom-Json
foreach($property in $runtime.environment.PSObject.Properties){[Environment]::SetEnvironmentVariable($property.Name,$property.Value,'Process')}
Set-Location -LiteralPath $ProjectPath
'@ | Set-Content -LiteralPath $terminal -Encoding UTF8
    $shell=New-Object -ComObject WScript.Shell
    $shortcutBackup=Join-Path $run ('shortcut-backups-'+[Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $shortcutBackup | Out-Null
    $powerShell=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $activation=Join-Path $launchers 'Activate-Package.ps1'
    $updated=@()
    $shortcutFolders=@([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('StartMenu'),(Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'))
    foreach($file in @($shortcutFolders | Where-Object {Test-Path -LiteralPath $_} | ForEach-Object {Get-ChildItem -LiteralPath $_ -Filter '*.lnk' -Recurse -File -ErrorAction SilentlyContinue} | Sort-Object FullName -Unique)){
        $link=$shell.CreateShortcut($file.FullName)
        $previous=@($link.TargetPath,$link.Arguments,$link.WorkingDirectory)
        $package=$packages | Where-Object {$link.TargetPath.StartsWith($_.InstallLocation+'\',[StringComparison]::OrdinalIgnoreCase) -or $link.Arguments -match ('-PackageName\s+"?'+[Regex]::Escape($_.Name)+'(?:"|\s|$)')} | Select-Object -First 1
        if($package){
            $appId=if($package.Name -eq 'Claude'){'Claude'}else{'App'}
            $link.TargetPath=$powerShell
            $link.Arguments='-NoProfile -WindowStyle Hidden -File "'+$activation+'" -PackageName "'+$package.Name+'" -ApplicationId "'+$appId+'" -RuntimePath "'+$runtimePath+'"'
            $link.WorkingDirectory=$ProjectsPath
        }
        foreach($entry in $plan.roots | Sort-Object {([string]$_.source).Length} -Descending){
            foreach($field in @('TargetPath','WorkingDirectory')){
                $old=[string]$link.$field; $source=[string]$entry.source
                if($old.Equals($source,[StringComparison]::OrdinalIgnoreCase) -or $old.StartsWith($source+'\',[StringComparison]::OrdinalIgnoreCase)){$link.$field=[string]$entry.destination+$old.Substring($source.Length)}
            }
            $boundary=[Regex]::Escape([string]$entry.source)+"(?=`$|[\\/\s`"'])"
            $mappedDestination=[string]$entry.destination
            $link.Arguments=[Regex]::Replace($link.Arguments,$boundary,[System.Text.RegularExpressions.MatchEvaluator]{param($match) $mappedDestination},[Text.RegularExpressions.RegexOptions]::IgnoreCase)
        }
        if(($previous-join "`n") -ne (@($link.TargetPath,$link.Arguments,$link.WorkingDirectory)-join "`n")){
            Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $shortcutBackup ([Guid]::NewGuid().ToString('N')+'.lnk'))
            $link.Save(); $updated+=$file.FullName
        }
    }
    foreach($package in $packages){
        $appId=if($package.Name -eq 'Claude'){'Claude'}else{'App'}
        $link=$shell.CreateShortcut((Join-Path $launchers ($package.Name+'.lnk')))
        $link.TargetPath=$powerShell; $link.WorkingDirectory=$ProjectsPath
        $link.Arguments='-NoProfile -WindowStyle Hidden -File "'+$activation+'" -PackageName "'+$package.Name+'" -ApplicationId "'+$appId+'" -RuntimePath "'+$runtimePath+'"'
        $link.Save()
    }
    $link=$shell.CreateShortcut((Join-Path $launchers 'AI Terminal.lnk'))
    $link.TargetPath=$powerShell; $link.WorkingDirectory=$ProjectsPath
    $link.Arguments='-NoProfile -NoExit -File "'+$terminal+'" -RuntimePath "'+$runtimePath+'" -ProjectPath "'+$ProjectsPath+'"'
    $link.Save()
    $pathEntries=@([string]$runtime.environment.npm_config_prefix)
    foreach($entry in ([string]$envBackup['Path'] -split ';' | Where-Object {$_})){
        $changed=$entry
        foreach($root in $plan.roots){
            $source=[string]$root.source
            if($changed.Equals($source,[StringComparison]::OrdinalIgnoreCase) -or $changed.StartsWith($source+'\',[StringComparison]::OrdinalIgnoreCase)){$changed=[string]$root.destination+$changed.Substring($source.Length);break}
        }
        $pathEntries+=$changed
    }
    [Environment]::SetEnvironmentVariable('Path',(($pathEntries | Select-Object -Unique)-join ';'),'User')
    Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class StorageEnvironmentNotify { [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessageTimeout(IntPtr h,uint m,IntPtr w,string l,uint f,uint t,out IntPtr r); }'
    $result=[IntPtr]::Zero
    [StorageEnvironmentNotify]::SendMessageTimeout([IntPtr]0xffff,0x1a,[IntPtr]::Zero,'Environment',2,5000,[ref]$result) | Out-Null
    $explorer=New-Object -ComObject Shell.Application
    $pins=$explorer.Namespace('shell:::{679f85cb-0220-4080-b29b-5540cc05aab6}')
    if($pins){
        foreach($pin in @($pins.Items())){
            foreach($root in $plan.roots | Where-Object category -eq 'project'){
                $old=[string]$pin.Path; $source=[string]$root.source
                if($old.Equals($source,[StringComparison]::OrdinalIgnoreCase) -or $old.StartsWith($source+'\',[StringComparison]::OrdinalIgnoreCase)){
                    $pin.InvokeVerb('unpinfromhome')
                    $folder=$explorer.Namespace([string]$root.destination+$old.Substring($source.Length))
                    if($folder){$folder.Self.InvokeVerb('pintohome')}
                }
            }
        }
    }
    foreach($window in @($explorer.Windows())){
        if($window.FullName -and [IO.Path]::GetFileName($window.FullName) -eq 'explorer.exe'){
            $old=[string]$window.Document.Folder.Self.Path
            foreach($root in $plan.roots){
                $source=[string]$root.source
                if($old.Equals($source,[StringComparison]::OrdinalIgnoreCase) -or $old.StartsWith($source+'\',[StringComparison]::OrdinalIgnoreCase)){$window.Navigate2([string]$root.destination+$old.Substring($source.Length));break}
            }
        }
    }
    # Verify an actual child-process temp write; command output is private evidence.
    & $PythonPath -c 'import tempfile,pathlib,os,json; f=tempfile.NamedTemporaryFile(delete=False); f.write(b"proof"); f.close(); p=pathlib.Path(f.name); assert p.parent.resolve()==pathlib.Path(os.environ["TEMP"]).resolve(); p.unlink(); print(json.dumps({"temp_write":str(p),"uv_cache":os.environ["UV_CACHE_DIR"],"pip_cache":os.environ["PIP_CACHE_DIR"],"npm_cache":os.environ["npm_config_cache"]}))' | Set-Content -LiteralPath (Join-Path $run 'future-write-proof.json') -Encoding UTF8
    if($LASTEXITCODE -ne 0){throw 'Fresh temp write did not verify'}
    @{runtime=$runtimePath;projects=$ProjectsPath;shortcuts=$updated;software='Windows-managed installers remain registered';sourceCleanup='Run retire after checking reopened apps';configureOnly=[bool]$ConfigureOnly} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $run 'setup-complete.json') -Encoding UTF8
    Save-Phase 'ready' 98 'Storage setup verified. Reopen apps and terminal tabs from the new launchers; retire original backups after checking them.'
}catch{
    Save-Phase 'needs-attention' 0 ('Setup stopped: '+$_.Exception.Message)
    throw
}
