[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PackageName,
      [Parameter(Mandatory=$true)][string]$ApplicationId,
      [string]$RuntimePath,[string]$ReceiptPath)
$ErrorActionPreference='Stop'
if($RuntimePath){
    $runtime=Get-Content -LiteralPath $RuntimePath -Raw|ConvertFrom-Json
    if($runtime.schema -ne 1){throw 'Unsupported runtime schema'}
    foreach($property in $runtime.environment.PSObject.Properties){
        if($property.Name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$' -or -not [IO.Path]::IsPathRooted([string]$property.Value)){throw 'Invalid runtime storage variable'}
        [IO.Directory]::CreateDirectory([string]$property.Value)|Out-Null
        [Environment]::SetEnvironmentVariable($property.Name,[string]$property.Value,'Process')
    }
}
$package=Get-AppxPackage -Name $PackageName
if(@($package).Count -ne 1){throw 'Expected one registered package'}
$manifest=Get-AppxPackageManifest -Package $package.PackageFullName
$apps=@($manifest.SelectNodes("//*[local-name()='Applications']/*[local-name()='Application']"))
if(-not @($apps|Where-Object{$_.GetAttribute('Id') -eq $ApplicationId}).Count){throw 'Application ID is not in the registered manifest'}
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[ComImport,Guid("2E941141-7F97-4756-BA1D-9DECDE894A3D"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IStorageActivation {
 [PreserveSig] int ActivateApplication([MarshalAs(UnmanagedType.LPWStr)] string id,[MarshalAs(UnmanagedType.LPWStr)] string args,uint options,out uint pid);
}
public static class StoragePackageActivation {
 public static uint Activate(string id) {
  object obj=Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")));
  try {uint pid;int hr=((IStorageActivation)obj).ActivateApplication(id,"",0,out pid);Marshal.ThrowExceptionForHR(hr);return pid;}
  finally {Marshal.FinalReleaseComObject(obj);}
 }
}
'@
$appProcessId=[StoragePackageActivation]::Activate($package.PackageFamilyName+'!'+$ApplicationId)
if($ReceiptPath){
    [IO.File]::WriteAllText($ReceiptPath,(@{utc=[DateTime]::UtcNow.ToString('o');processId=$appProcessId;package=$PackageName;installLocation=$package.InstallLocation;runtime=$RuntimePath;method='IApplicationActivationManager'}|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
}
Write-Output ('Activated '+$PackageName+' (PID '+$appProcessId+')')
