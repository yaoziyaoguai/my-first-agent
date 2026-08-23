---
title: 让 Agent 跑本地命令，难点从来不是 subprocess
slug: governed-local-action-beyond-subprocess
excerpt: 从结构化命令、精确授权、崩溃恢复到完成证据，复盘 my-first-agent 如何给本地执行划出一条诚实的安全边界。
tags:
  - Agent Engineering
  - Local-first
  - Safety
  - Python
date: 2026-08-23
---

# 让 Agent 跑本地命令，难点从来不是 subprocess

让 Agent 执行一条本地命令，最短的实现也许只有一行：把模型生成的字符串交给 shell。真正麻烦的是下一秒开始出现的问题：这条命令究竟批准了什么？程序超时后有没有残留子进程？Agent 崩溃重启后能不能安全重试？退出码为 0，是否真的等于任务完成？

我在 `my-first-agent` 中实现受治理的本机行动时，最终没有把目标定义成“支持 shell”，而是只增加一个 `local_process` 工具。它仍然在唯一的 Agent Runtime 中工作，只接受结构化参数，并沿用已有的审批、checkpoint、恢复和证据链路。

这篇文章不试图证明它是一个强沙箱。恰恰相反，它记录的是：在没有 OS sandbox 的前提下，怎样把能力边界说准确，把不能证明的事情停在不能证明的位置。

## 先定义不做什么

这个能力明确不支持 command string、pipeline、redirection、interactive TTY、后台任务和任意环境变量注入。模型只能提交四个字段：

```json
{
  "executable": "python",
  "argv": ["-m", "pytest", "-q"],
  "cwd": ".",
  "profile": "standard"
}
```

这不是为了让接口看起来整洁，而是为了删除一整类含糊语义。`argv` 中即使出现 `;`、`|`、`$()` 或换行，它们也只是 literal arguments，不会被第二层 shell 再解释。

同时，获批程序仍以当前 OS user 身份运行。`cwd` 只是起始目录，不是文件系统隔离；子进程仍可能访问同一用户有权访问的其他文件、建立网络连接或派生进程。这条限制会直接展示在批准信息里，而不是用“安全执行”四个字带过。

## 第一层：模型只能描述结构化命令

`local_process` 的 Tool schema 是 closed shape：只允许 `executable`、`argv`、`cwd` 和 `profile`，多一个字段都会被拒绝。资源限制也不是模型可以任意填写的数字，而是 `short`、`standard`、`long` 三个固定档位。

这里有一个容易忽略的设计点：安全不是靠维护一份 shell metacharacter 黑名单。黑名单永远会漏，真正的边界是从协议层取消 shell parsing，最终调用保持 `shell=False`。

这也让批准页面能够展示 exact executable、ordered argv、cwd 和资源档位。用户批准的是一条可读、可比较的结构化请求，而不是一段事后很难解释的字符串。

## 第二层：批准绑定命令身份

只比较命令文本仍然不够。`python` 在不同的 `PATH` 下可能解析成不同文件；同一路径的 executable 也可能在批准后被替换；cwd 甚至可能经历一次 `rm + mkdir`，路径没变，底层目录已经不是原来的 inode。

因此 admission 阶段会把命令解析为更具体的 identity：

- executable 的 canonical path、symlink chain、stat 信息和有界 SHA-256；
- ordered argv、cwd descriptor、resource profile 和 environment policy；
- 由这些字段计算出的 command fingerprint。

在真正 spawn 前，系统会紧邻执行点重新解析 executable 和 cwd。任何 identity drift 都返回 `KnownNotExecuted`，要求重新批准，不会假装旧授权仍然有效。

子进程环境则从 allowlist 构造，只传隔离的 `HOME`、`TMPDIR`、清洗后的 `PATH`、locale 和时区。Provider key、proxy、SSH agent、云凭据等 ambient environment 不会被主动继承。它减少的是意外泄露，不应被误解成进程无法从其他渠道访问同 UID 资源。

## 授权不是 yes，而是一份短租约

一次 `yes` 不会变成永久权限。Runtime 从当前待审批请求铸造一份 durable lease，并精确绑定 Goal、Goal revision、workspace identity、command fingerprint、批准请求、过期时间和剩余次数。

租约没有 wildcard、prefix 或“这个目录下都可以”的模糊匹配。换一个 argv、切换资源档位、修正 Goal、暂停或取消任务，原租约都会失效。使用次数在 intent 进入持久化的 `EXECUTING` checkpoint 时单调消耗，而不是等程序跑完才记账。

这样做解决了一个恢复语义问题：如果 checkpoint 已经写下“准备执行”，随后进程启动但 Agent 崩溃，重启后不能因为没有看到结果就把同一权限再消费一次。系统必须先承认自己不知道上次 effect 的结果。

## 执行不是 subprocess.run，而是受控生命周期

Runner 的职责被刻意限制：它不懂 Goal、审批或模型，只接收已经 admission 的 immutable spawn request，返回 closed execution draft。

执行时关闭 stdin，不创建 TTY，建立新的 process group，并同时限制 wall time、stdout、stderr、合并输出和最终渲染字符数。超时后按 `TERM → KILL → reap` 处理整个已观察到的进程组。

最关键的不是“发出了 KILL”，而是能否确认进程组已经消失。只有明确观察到 group gone，结果才能分类为 `timed_out_reaped`。清理状态无法确认时，系统进入 unknown outcome，而不是生成一张看起来完整的成功回执。

输出也是不可信数据。它会被有界采集、计算 digest，并以确定性的 UTF-8 replacement 方式投影。无效编码、控制字符或无限输出都不能把 Runtime 变成新的不受控输入通道。

## 不知道结果时，不重试

对纯计算函数来说，失败后重试通常是合理默认值；对本地副作用不是。

如果 spawn 之后发生异常，或者 Agent 重启时看到 durable `EXECUTING` 状态，却找不到可信的 result checkpoint，系统只能确认“可能执行过”。此时自动重放可能重复写文件、重复提交或重复发送外部请求。

所以 unknown outcome 会停下来，要求用户分类为 success、failed 或 stop。这个回答用于恢复状态，但不会凭空生成缺失的 process receipt，也不会删除原本的验收义务。

这是一种不那么“丝滑”的体验，却是一条重要的可靠性边界：恢复的目标不是让流程继续动，而是避免用猜测覆盖已经发生过的现实。

## 完成不能靠模型自报

进程 exit 0 只说明程序正常退出，不说明用户目标已经完成。`pytest` 退出 0 可以证明一次测试运行成功，却不能自动证明目标文件包含预期内容；一个脚本打印 `done` 更不能成为权威证据。

因此 Kernel 会从 verified intent 和 validated draft 铸造 `ProcessReceiptV1`，绑定 Goal、lease、command identity、outcome、退出状态、输出 digest 和进程组清理状态。Runtime 的 evidence oracle 只接受 closed receipt fields，并根据 Goal 的 mandatory criteria 决定是否能够显示 `VERIFIED_DONE`。

如果任务要求生成文件，还需要文件 read-back 等额外证据。模型说“完成了”、普通 tool metadata、伪造 receipt、错误 Goal 的 receipt，都会被拒绝。

## 验证这套边界，而不是验证 demo

这类能力最容易写出一个漂亮 demo：运行 `echo hello`，看到输出，然后宣布成功。我的测试重点放在相反方向：

- argv 中的 shell 字符必须保持 literal；
- executable 或 cwd 在批准后漂移必须 zero-spawn；
- 拒绝请求不能留下可复用租约；
- lease 必须限次、过期、可撤销，并绑定当前 Goal revision；
- 超时必须处理并确认 observed process group；
- 崩溃恢复不能自动重放 unknown effect；
- exit 0 不能绕过 evidence-backed completion。

在离线合同之外，我还保留了真实 Provider journey 来验证模型能否在同一个自然语言入口中正确请求结构化执行、等待 exact approval、消费已有租约，并在改变命令时重新请求授权。Mock 可以保护实现合同，但不能替代真实模型在权限边界上的行为证据。

## 我现在怎样理解 Agent 的本地执行

本地执行不是给 Agent 加一个更强的工具，而是增加一种新的 authority。工具 schema 只是入口，真正的产品语义分散在批准、持久化状态、执行生命周期、恢复和完成判定之间。

这次实现后，我更愿意用下面这条链路描述它：

```text
structured request
  → admission and identity
  → exact human approval
  → finite Goal-scoped lease
  → durable EXECUTING checkpoint
  → bounded process lifecycle
  → Kernel-minted receipt
  → evidence-backed completion
```

任何一段缺失，Agent 都可能“看上去能做事”，却无法在重启、漂移或失败时解释自己究竟做了什么。

目前这仍是一条 POSIX/macOS-first、operator-trusted、same-UID 的边界，不是 OS sandbox。下一步真正值得探索的也不是扩大命令范围，而是继续观察：这些精确授权在日常任务里是否足够易懂，unknown outcome 是否能被普通用户正确处理，以及更强隔离是否值得它带来的复杂度。
