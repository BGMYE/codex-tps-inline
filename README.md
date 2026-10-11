# Codex TPS Inline · Windows / macOS · 0.4.0

在 Codex 原生工具栏中、**「新建标签页」左侧**加入「TPS 开 / TPS 关」按钮，在每轮回复下方显示平均 TPS。按钮参与工具栏布局，为原生按钮留出空间。切换对话自动显示，无需逐个对话调用技能。

- 点击关闭：隐藏状态行并暂停读取 token 日志，按钮继续保留。
- 点击开启：恢复统计和每秒刷新。
- 开关状态会记住，并同步到同一渲染目录中的其他窗口。
- 运行中显示本轮均值和计数延迟，完成后保留最终均值。

最终回复尚未出现时，实时状态行位于输入区上方；回复出现后移到对应回复下方。回填最近 200 轮。

![Codex 内嵌 TPS 开关](validation/windows-tps-on.png)

## 获取代码

下载并解压 GitHub 仓库的 ZIP，或执行：

```bash
git clone https://github.com/BGMYE/codex-tps-inline.git
cd codex-tps-inline
```

在项目目录中按系统运行以下安装命令。

## Windows 安装

需要 Codex 桌面版、Python 3.10+ 和支持 `codex plugin` 的 CLI。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

安装器会在桌面和用户开始菜单建立 **Codex** 快捷方式。以后从这些入口打开 Codex，启动器会同时启动客户端与 TPS 后台，无需另开插件或调用技能；重复打开会复用现有 TPS 窗口。原有同名 `.lnk` 会备份，卸载时恢复。旧的 **Codex TPS** 入口也继续可用。

原 Microsoft Store 入口和已有任务栏固定图标仍可能绕过启动器。若使用任务栏，请将新建的 Codex 快捷方式固定到任务栏，之后从该图标启动。安装器不注册登录时运行的观察器。

**从 0.3.x 升级：** 先完成当前工作，完整退出原来的所有 Codex 窗口，再从新建的 Codex 快捷方式打开一次。0.4.0 使用原生数据目录；旧版专用窗口要等退出后才会停止使用旧目录。旧目录保留，不会删除其中的数据。

## macOS 安装

需要可正常运行的 Codex 桌面版、Python 3.10+ 和支持 `codex plugin` 的 CLI。安装器也会尝试使用应用附带的 CLI，无需额外 Python/npm 运行库。

解压安装包，在此目录执行一次：

```bash
bash install-mac.sh
```

打开 **~/Applications/Codex TPS.app**，将它拖到 Dock 作为日常启动入口。每次从这个入口重新打开 Codex，TPS 会一起启动；之后使用 Codex 内的 TPS 按钮随时开关统计。原 `/Applications/Codex.app` 的入口不会自动加载此扩展。

适配会检测 `/Applications` 和 `~/Applications` 内的 `Codex.app` / `ChatGPT.app`。Mac 启动参数、路径和 Finder 应用生成已通过模拟平台测试；**当前环境只有 Windows，尚未做 Mac 真机验证**。

## 启动方式与开关

Windows 使用 MSIX 应用激活接口，macOS 使用 `open -a`。启动参数开放 `127.0.0.1` 本机渲染连接。两者均使用 Codex 原生数据目录和实例机制，统计读取原来的 `CODEX_HOME`。

已有 TPS 连接时，启动器只将现有窗口带到前台；重复点击入口或调用技能不会再次激活应用。有多个窗口时，优先聚焦已打开目标对话的窗口，统计会跟随当前对话。0.3.x 的独立目录会导致普通入口或通知点击启动另一个实例，0.4.0 已移除这个设置。

**普通 Codex 已经运行且没有 TPS 连接时，Windows 启动器会提示完整退出后重新打开，不会另开一个 TPS 实例。** 原商店入口的冷启动仍不会自动添加 TPS 参数。此模式属于本机 DOM 扩展，未修改客户端安装包；它不是官方原生状态栏扩展 API，未来客户端改变启动方式或页面结构时可能需要适配。

`$tps` 用于查询当前/上一轮统计和诊断，直接点击按钮不调用模型。按钮关闭时后台保持轻量连接，以便再次开启。完全停止后台使用 `control.py stop`，这会移除按钮和状态行。

## 测速口径

**平均 TPS = 本轮输出 token ÷ 本轮总耗时（秒）。**

每秒刷新的是本轮均值。Codex 在一次模型请求结束时才报告 token，长输出期间计数会滞后；未报告时显示“—”。它不是每秒实际新生成 token 的数量，也不是服务端纯解码 TPS。

完成后优先使用 `task_complete.duration_ms`。输出已包含推理与模型工具调用，不重复相加；不计输入、缓存输入和工具返回。耗时包含工具和请求等待，各对话、各轮任务及子 Agent 分开统计。

用量来自新版 `token_usage_record.turn_token_usage`，兼容旧版 `token_count`。统计代码只读本机 SQLite 和会话 JSONL，不读取认证文件、不上传聊天内容。渲染只传入数值、模型名和匹配 ID。

## 诊断与卸载

```text
<Python解释器> plugins/codex-tps-inline/scripts/control.py inspect --thread <对话ID>
<Python解释器> plugins/codex-tps-inline/scripts/control.py stop
```

Windows 使用 `python`，macOS 使用 `python3`。状态目录分别为 `%LOCALAPPDATA%/CodexTPSInline` 和 `~/Library/Application Support/CodexTPSInline`，包含 `status.json`、`launch-result.json` 和启动日志。

`fresh=true` 为新鲜心跳；对应对话 `stage=rendered`、`rendered>0`、`toggle_rendered=true` 表示状态行和按钮已匹配。`stage=disabled` 表示用户关闭统计，属于正常状态。

Windows 卸载执行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1`，Mac 执行 `bash uninstall-mac.sh`。渲染数据目录保留，卸载后使用原 Codex 入口即可。

## GitHub 项目参考

| 项目 | 显示方式 | 平台 / 限制 |
| --- | --- | --- |
| [Mie-coder/codex-tps](https://github.com/Mie-coder/codex-tps) | 回复底部统计 | 原完整方案面向 macOS；本项目保留 MIT 归属，扩展双平台启动和内嵌开关 |
| [KDB-Wind/codex-tps](https://github.com/KDB-Wind/codex-tps) | 每轮完成统计，支持 $tps | 主要使用 CLI Hook |
| [Javis603/token-monitor](https://github.com/Javis603/token-monitor) | 独立常驻 UI | 支持 Windows |
| [strobil/CodexTPS](https://github.com/strobil/CodexTPS) | macOS 菜单栏 | macOS 14+ Apple Silicon |

参考源码于 2026-10-10 核对。测试与实际运行证据见 [VALIDATION.md](VALIDATION.md)。MIT；见 LICENSE、NOTICE。
