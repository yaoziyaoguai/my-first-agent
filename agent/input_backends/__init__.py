"""输入后端包：把不同终端入口统一成 UserInputEvent。

后端只负责 I/O 适配，不负责 Runtime 语义。simple 后端保留旧 input()
和 /multi 协议；textual 后端提供轻量 TUI 输入容器。二者都应该返回
agent.user_input.UserInputEvent，让 main loop 再决定是否进入 Runtime。
"""
