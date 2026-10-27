param([switch]$NoOpen)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskArguments=@((Join-Path $taskRoot 'scripts\launcher.py'))
if($NoOpen){$taskArguments+='--no-open'}
if(Get-Command py -ErrorAction SilentlyContinue){& py -3 @taskArguments}
elseif(Get-Command python -ErrorAction SilentlyContinue){& python @taskArguments}
else{throw 'Please install Python 3.11 or newer.'}
if($LASTEXITCODE -ne 0){throw 'Startup failed. See data/logs/.'}
