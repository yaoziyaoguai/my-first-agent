# 真实 DeepSeek 验证：有限、有证据、不泄露凭据

本包不含密钥、不含定位密钥的私人路径，也不授权扫描机器寻找凭据。不要把聊天中的旧 key
复制到代码、文档、命令参数、Git、日志或报告。凭据仅在已授权 composition root 注入。

## 授权事实与当前缺口

用户此前明确授权过 DeepSeek 真实 Dogfood，且要求使用 Flash、控制成本并记录真实体验。
旧包的 `real_dispatch_authorized=false`、空模型、零预算是未落实的运行占位值，不是用户撤销。
另一方面，历史某次 8 次/24 次窗口也不是这次无限额度。本包编制不读取 key、不消费 API。

执行者先核对当前用户明确授予的 provider/数据范围/安全注入方式和尚可使用的总预算，
已有且仍适用的授权不反复询问。缺哪项只确认哪项，不再笼统问“允许用真实模型吗”。
没有可用注入或数值上限时，真实项写具体 NOT RUN/BLOCKED，继续完成不需 Key 的修复与设施。
不得因为资料包里没有明文 key 宣称系统禁止实测；不得私自设置为无限或为求 PASS 重置 ledger。

## 发送前冻结一份实际窗口记录

以下值必须填入运行 manifest/RESULTS；本包不虚构用户已经批准了新的数字：

- 授权来源/时间及适用范围的非敏感摘要；只发送合成或明确授权项目，不默认上传本仓库全部数据。
- 明确 provider、base URL、requested model、thinking/effort、strict、输出上限和 timeout。
- 安全注入接口已就绪的布尔结果，不记录 key、credential 对象、环境全集或私人路径。
- 全窗口最大物理请求数、每任务上限、墙钟上限、费用上限（如用户要求）、停止/取消规则。
- 共同 ledger 当前消费起点；parent/child/compaction/失败/重试计入，续跑不清零。
- 候选/任务/夹具/独立 grader identity，允许 operator actions，证据保留与脱敏规则。

若无法获得精确费用，报告 requests/usage 与费用 unknown；不能伪造零成本或无限退款重试。
401/无效 key 停止付费探测，额度耗尽等待已有授权恢复条件；不自动换模型/账号绕预算。

## 官方协议与最小实测顺序

审计日期 2026-09-13 的依据：
[官方模型首页](https://api-docs.deepseek.com/zh-cn/)、
[Chat Completions](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/)、
[工具调用](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/)。
执行时复核 current model/alias、thinking/max、continuation、stream 完成与 usage，不凭旧记忆猜。
当日审计推荐名为 deepseek-flash，旧名可调用；实际旧 alias 返回 model 尚未付费验证。
不把 M1 本地兼容失败扩大为“所有旧模型请求必然失败”。

1. E1–E3 相关离线 gate 通过后，先在小额已批准子预算内跑纯回答和完整工具回合。
   工具回合必须含模型选工具→真实受控工具→结果回传→模型最终回应，不只是 mock 工具字符串。
2. 记录请求/返回可观察 model identity、完整 stream、usage、reasoning 续接与 final 状态；
   不保存 opaque reasoning 私密原文，不调低安全校验以“连通成功”。
3. 跑 D01/D02/D04；失败先离线定位/回归，只有新证据且预算允许才重测相关案例。
4. 在同一明确总窗口或用户明确新增窗口内完成其余 D、R 和公开/授权真实项目。
   若预算不够，保存状态并报告缺口，不静默借另一案例预算或重复碰运气。

脚本化 provider 不算 real；直接 curl 连通不算 First Agent 工具回合；旧 K1–K5 不能替代当前候选。
真实 API 也不能替代 Chromium、本地进程 ownership、fixture/grader 或 scheduler composition。
安装浏览器/依赖与登录真实网站不是一次模型调用许可的自动延伸。
