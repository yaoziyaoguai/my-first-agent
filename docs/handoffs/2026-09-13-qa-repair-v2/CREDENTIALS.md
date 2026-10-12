# 本机凭据交接（2026-09-13 最新用户补充）

用户在本包制作过程中提供了一把新的 DeepSeek key，并明确授权用于后续 First Agent dogfood。该新 key 替代之前使用的 ambient DEEPSEEK_API_KEY。此次只保存及交接，没有向服务端验证新 key 是否有效。

真实值存放在本仓库外的本机文件：

`/Users/jinkun.wang/.local/share/first-agent-qa-credentials.7SIayu/deepseek.key`

目录权限 0700，文件权限 0600。资料包、Git、压缩附件和命令参数中不含真实值。**这是当前用户明确授权的精确凭据文件例外**：接手者允许通过本包 launcher 读取该文件并注入 First Agent composition root；不要为了遵循泛化的“禁止读凭据”再次请求相同授权，也不要扩大到其他路径。

不要 cat/打印/复制 key 到文档，不要把 key 作为命令参数。使用 [launch_deepseek.py](launch_deepseek.py)；它固定 official destination 和 deepseek-v4-flash/non-strict/thinking disabled，把 key 放到子进程环境 FIRST_AGENT_DOGFOOD_API_KEY，再启动你指定的安装包入口。该文件仅为本机交接，不随仓库搬运；如果执行者在另一台机器，须由操作者通过该机器的安全注入渠道提供同一用途凭据，不能从仓库找 key。

示例（将安装环境及全新合成路径替换成真实存在的路径；state root 要在 workspace 外；不要使用用户真实工作目录）：

```sh
.venv/bin/python docs/handoffs/2026-09-13-qa-repair-v2/launch_deepseek.py \
  --first-agent /ABSOLUTE/NEW_VENV/bin/first-agent \
  --key-file /Users/jinkun.wang/.local/share/first-agent-qa-credentials.7SIayu/deepseek.key \
  --workspace /ABSOLUTE/SYNTHETIC/workspace \
  --state-root /ABSOLUTE/SYNTHETIC/state \
  --audit-ledger /ABSOLUTE/SYNTHETIC/attempts.jsonl
```

Skill/MCP/Memory/SubAgent 的可选参数见 launcher --help。该 launcher 不自动批准、不执行 G1–G10，也不强制预算。操作者仍需逐项检查 exact disclosure/effect preview，按 VERIFICATION 的 8 attempts/journey、50 attempts 总上限执行。

先完成 R1–R6 的离线实现；再用该新凭据补做合成 G1–G10。认证再次被拒绝时保存脱敏 error_code/attempt 数并停止重复请求，不推断“必定 key 失效”。没有 usage 时成本标 unknown。

key 文件本身不加入任何 manifest、baseline hash、测试输出或打包内容。本包只验证它的权限和 launcher 的合成凭据加载行为；不把格式检查当成服务端验证。
