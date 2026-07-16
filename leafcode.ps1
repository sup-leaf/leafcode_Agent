#!/usr/bin/env pwsh
$script = Join-Path $PSScriptRoot "agent_tui_v4.py"
if ($MyInvocation.ExpectingInput) {
  $input | & python $script $args
} else {
  & python $script $args
}
exit $LASTEXITCODE
