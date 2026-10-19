# 连接 ChatGPT Tunnel

## 使用目标

把本机已授权能力连接到 ChatGPT。

## 开始前

准备已有 Tunnel ID 与带 Tunnels Read + Use 权限的 Runtime App Key。不要把密钥写入笔记。

## 操作步骤

1. 桌面端打开 **设置 → AI 连接 → ChatGPT 连接**。
2. 填入 Tunnel ID 和 Runtime App Key，选择 **保存并连接**。安装包内置运行时。
3. 通道就绪后，在 ChatGPT 添加自定义 MCP 服务，选择 Tunnel、相同 ID 和 No authentication，并在聊天中启用。
4. 在 LeafLoom 分别开启该连接的笔记、飞书读取及所需写入权限。
5. 用虚构笔记完成一次实际工具调用，核对返回的权限与内容。

## 完成后的表现

关闭窗口后连接留在托盘；退出应用会停止。连接就绪不等于工具调用已经成功。

## 没有成功时

同一个共享配置只运行一个受管实例。权限变更后刷新客户端工具；断开连接会关闭自动连接。清除配置前先核对范围。

## 下一步

- [管理 MCP 权限与访问凭据](permissions.md)
- [连接本机 MCP 客户端与 Skill](mcp.md)
- [排查 AI、MCP、Tunnel 与飞书连接](connection-problems.md)
