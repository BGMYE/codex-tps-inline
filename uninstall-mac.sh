#!/bin/bash
set -euo pipefail
if [ "$(uname -s)" != Darwin ]; then
  echo '此卸载脚本用于 macOS。' >&2
  exit 1
fi
tps_source=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
tps_python=$(command -v python3)
tps_control="$tps_source/plugins/codex-tps-inline/scripts/control.py"
tps_cli=$(command -v codex || true)
if [ -z "$tps_cli" ]; then
  tps_bundle=$("$tps_python" "$tps_control" app-info | "$tps_python" -c 'import json,sys; print(json.load(sys.stdin)["bundle"])')
  tps_cli="$tps_bundle/Contents/Resources/codex"
fi
"$tps_python" "$tps_control" stop
"$tps_python" "$tps_source/plugins/codex-tps-inline/scripts/mac_launcher.py" remove
"$tps_cli" plugin remove 'codex-tps-inline@local-tps-inline'
"$tps_cli" plugin marketplace remove 'local-tps-inline'
echo '插件及 Finder 启动入口已移除。渲染数据目录保留。'
