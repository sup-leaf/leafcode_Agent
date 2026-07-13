#!/usr/bin/env pwsh
$script = "D:\agent-demo-link\agent_tui_v4.py"
if ($MyInvocation.ExpectingInput) {
  $input | & python $script $args
} else {
  & python $script $args
}
exit $LASTEXITCODE
