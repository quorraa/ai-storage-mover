# Exercise the actual status function without invoking migration or changing user settings.
$ErrorActionPreference='Stop'
$runs=Join-Path (Split-Path $PSScriptRoot -Parent) '.runs'
$run=Join-Path $runs ('windows-status-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $run -Force | Out-Null
try{
    $errorsFound=$null;$tokens=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Split-Path $PSScriptRoot -Parent) 'src\ai_storage_mover\Setup-Storage.ps1'),[ref]$tokens,[ref]$errorsFound)
    if($errorsFound.Count){throw 'Setup parse errors'}
    $function=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Save-Phase'},$true)
    if(-not $function){throw 'Actual status function not found'}
    # The parsed source above belongs to this checkout, not an external document.
    . ([ScriptBlock]::Create($function.Extent.Text))
    @{percent=90;roots=@{keep=@{destination='unchanged'}}} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $run 'state.json') -Encoding UTF8
    Save-Phase 'configuration' 91 'First status write'
    Save-Phase 'browser-state' 93 'Replace an existing status'
    Save-Phase 'needs-attention' 0 'Progress must stay measured'
    $status=Get-Content -LiteralPath (Join-Path $run 'status.json') -Raw | ConvertFrom-Json
    $state=Get-Content -LiteralPath (Join-Path $run 'state.json') -Raw | ConvertFrom-Json
    if($status.percent -ne 93 -or $state.percent -ne 93 -or $status.phase -ne 'needs-attention' -or $state.roots.keep.destination -ne 'unchanged'){throw 'Native status invariants failed'}
    'Windows setup status fixtures passed: atomic replacement, preserved journal, monotonic progress.'
}finally{
    $absolute=[IO.Path]::GetFullPath($run)
    $parent=[IO.Path]::GetFullPath($runs)
    if(-not $absolute.StartsWith($parent+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Fixture cleanup path escaped .runs'}
    Remove-Item -LiteralPath $absolute -Recurse -Force
}
