$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location "$projectRoot\backend"
python -m pytest tests_command -q
if ($LASTEXITCODE) { throw 'Backend checks failed.' }
Set-Location "$projectRoot\frontend"
npm run build
if ($LASTEXITCODE) { throw 'Web build failed.' }
Set-Location "$projectRoot\mobile"
npm run typecheck
if ($LASTEXITCODE) { throw 'Mobile TypeScript failed.' }
npm run export
if ($LASTEXITCODE) { throw 'Mobile bundle export failed.' }
