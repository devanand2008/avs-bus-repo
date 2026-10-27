$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
python "$projectRoot\scripts\launch.py" @args
exit $LASTEXITCODE
