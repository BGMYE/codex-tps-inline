#!/bin/bash
set -euo pipefail
if [ "$(uname -s)" != Darwin ]; then
  echo '此安装脚本用于 macOS。' >&2
  exit 1
fi
tps_source=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
tps_python=$(command -v python3)
"$tps_python" -c "import sys; assert sys.version_info >= (3, 10), 'Requires Python 3.10+'"
tps_control="$tps_source/plugins/codex-tps-inline/scripts/control.py"
tps_cli=$(command -v codex || true)
if [ -z "$tps_cli" ]; then
  tps_bundle=$("$tps_python" "$tps_control" app-info | "$tps_python" -c 'import json,sys; print(json.load(sys.stdin)["bundle"])')
  tps_cli="$tps_bundle/Contents/Resources/codex"
fi
if [ ! -x "$tps_cli" ]; then
  echo '需要 Codex CLI。请先安装 CLI，再执行本脚本。' >&2
  exit 1
fi
"$tps_python" "$tps_control" stop
"$tps_cli" plugin marketplace add "$tps_source" --json
"$tps_cli" plugin add 'codex-tps-inline@local-tps-inline' --json
tps_codex_home=${CODEX_HOME:-"$HOME/.codex"}
tps_installed="$tps_codex_home/plugins/cache/local-tps-inline/codex-tps-inline/0.4.0/scripts"
"$tps_python" "$tps_installed/mac_launcher.py" install --home "$tps_codex_home"
"$tps_python" "$tps_installed/control.py" restart --home "$tps_codex_home"
echo '安装完成。将 ~/Applications/Codex TPS.app 拖到 Dock，以后从此图标打开 Codex，TPS 会自动启动并记住上次开关状态。原 Codex.app 入口不会被替换。'
