---
name: tps
description: 查看 Codex 当前对话的任务输出 token、平均 TPS，以及回复下方嵌入状态行的运行情况。用于 $tps、查看输出速度或回复底部 TPS；通过本机连接在 Codex 内显示，不打开外部窗口。
---

统计与显示脚本位于本技能目录的 `../../scripts/control.py`。Windows 使用 `python`，macOS 使用 `python3`。调用 `$tps` 时，用当前 `CODEX_THREAD_ID`（缺失时用 `CODEX_SESSION_ID`）执行：

```powershell
python "<本技能目录>/../../scripts/control.py" launch --thread "<当前对话 ID>"
python "<本技能目录>/../../scripts/control.py" inspect --thread "<当前对话 ID>"
```

简短报告 `session.current.output_tokens`、`elapsed_seconds`、`average_tps` 与状态。查询本身会开始新一轮；查看上一任务结束后的均值用 `session.last_finished`。

底部状态行由本机后台监控自动更新，无需每轮调用技能或模型。`launch` 首次打开使用独立渲染数据目录的 **Codex TPS 窗口**，之后复用该窗口；任务统计仍使用当前 `CODEX_HOME`。现有普通 Codex 进程不会阻止启用，不需要用户反复退出。开启后切换对话自动显示，技能用于查询和诊断。

Windows 安装器建立桌面和用户开始菜单的 **Codex** 快捷方式，重新从该入口打开时自动启动 TPS。旧 Codex TPS 入口继续可用。原 Store 入口及旧任务栏图标不会自动加载；不要将快捷方式集成描述成拦截所有原生入口。macOS 从 `~/Applications/Codex TPS.app` 启动，可固定到 Dock。无需在每个对话调用本技能。

检查 `monitor.fresh` 与当前 thread 对应的 diagnostics：只有 `stage=rendered` 且 `rendered>0` 才表示本对话已匹配到显示位置。`waiting_for_launcher` 表示还未连接到 TPS 窗口，应执行 `launch --thread`，不要再次要求用户完全退出。不要自动退出客户端或将“已安装”说成“已显示”。

`launcher`（若存在）是上次启动入口的记录，不代表当前显示状态。Windows MSIX 必须使用 `activate.ps1` 的应用激活接口；不能直接执行包里的 `ChatGPT.exe`。启动异常保存在 `%LOCALAPPDATA%/CodexTPSInline/launcher.log` 和 `launch-result.json`，诊断时可读取这些文件。

统计口径为本轮已报告输出 token / 本轮耗时，耗时包含工具与请求等待。输出已经包含推理与工具调用，不能再次相加。模型请求结束时才报告用量，所以运行中的均值会滞后；缺失或无效计数保持“不可用”。不要称为逐秒解码速度。

此插件通过启动参数开放的 127.0.0.1 本机渲染连接显示临时 DOM 状态行，未修改客户端安装包。用户需要停止显示时执行 `control.py stop`。不要改成独立小窗或浏览器面板。

原生工具栏「新建标签页」左侧的「TPS 开 / TPS 关」直接控制统计，状态会记住。按钮参与工具栏布局，找不到原生工具栏时不退回覆盖标题层。关闭时按钮保留并暂停读取 token 日志，不要在查询时覆盖用户的关闭偏好。诊断的 `stage=disabled` 是正常状态，`toggle_rendered=true` 才表示按钮已匹配。macOS 使用 `open` 启动，不执行 Windows 的 PowerShell 激活脚本。
