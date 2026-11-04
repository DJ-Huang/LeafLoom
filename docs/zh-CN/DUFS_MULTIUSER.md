# 一个 DUFS 容器，多个独立附件账号

[English](../en/DUFS_MULTIUSER.md) · [中文](DUFS_MULTIUSER.md) · [日本語](../ja/DUFS_MULTIUSER.md)

每个账号有独立的目录、附件原件和资料。例如 DJ 连接 `https://files.example.com/DJ/`，Alice 连接 `https://files.example.com/Alice/`。每人使用自己的 LeafLoom 和凭据。管理员通过服务器配置管理账号，不开放自行注册。

## 构建和验证

原版 DUFS 0.47.0 只拒绝越出整个服务根目录的符号链接，仍允许链接到根目录内的其他账号。新增独立用户前，应使用补丁镜像并保持 `allow-symlink: false`。补丁拒绝符号链接及路径中的链接父目录，在目录列表、搜索、打包和 COPY/MOVE 目标检查中使用相同限制；账号内部的符号链接也禁用。本方案信任 NAS 本机管理员和文件系统写入者，不防御恶意本机进程并发替换文件路径的竞争攻击。

在 ARM64 Docker 主机的仓库根目录执行：

```sh
docker build --platform linux/arm64 -t leafloom/dufs:0.47.0-symlink1 templates/dufs
python3 scripts/check_dufs_isolation.py --docker-image leafloom/dufs:0.47.0-symlink1
docker image save --platform linux/arm64 -o dufs-symlink1-arm64.tar leafloom/dufs:0.47.0-symlink1
```

x86-64 NAS 使用 `linux/amd64`。Dockerfile 固定上游源码校验值、构建镜像和 Cargo 锁文件；补丁版本显示为 `0.47.0-leafloom.1`。验证脚本只使用临时账号、文件和随机回环端口，不连接用户 NAS；需要 OpenSSL 生成测试密码哈希。验证返回非零时不部署。

## 现有内容归 DJ，保留密码

把[配置模板](../../templates/dufs/config.yaml.example)放到附件发布目录之外。将占位符替换成现有的**完整 SHA-512 crypt 密码哈希**，保留原密码及原有全局操作开关。本部署保留原件只读、`Incoming` 内附件与资料可写的保护：

```yaml
auth:
  - 'DJ:$6$REPLACE_WITH_EXISTING_SHA512_CRYPT_HASH@/DJ:ro,/DJ/Incoming:rw'
allow-symlink: false
```

按[Compose 模板](../../templates/dufs/compose.yaml.example)，将现有附件目录挂载为 `/data/DJ:ro`，现有 `Incoming` 挂载为 `/data/DJ/Incoming:rw`，私有配置目录挂载为 `/config:ro`。原件无需复制或搬动。不给账号授权 `/`，不添加匿名规则；密码、哈希、私人路径和恢复备份不进入 Git。

## 在极空间 Docker 中切换

1. 备份原容器、DUFS 配置和 LeafLoom 附件工作区。单独记录挂载只读状态：极空间导出的 YAML 可能遗漏只读标记。保留旧镜像和原配置。
2. 将已验证的镜像包、新配置及 Compose 文件上传到 NAS 配置目录，在 **Docker → 镜像 → 导入 → 从极空间导入** 中导入镜像。
3. 保存草稿并退出 LeafLoom，确认没有活动上传或资料写入，保留待传原件和任务记录。停止旧附件容器，关闭其开机自动启动，避免重启后争用同一端口。
4. 导入使用补丁镜像的 Compose 项目，沿用原端口、网络、资源限制和挂载读写状态。附件服务只运行一个容器；旧容器可停用保留作恢复副本。
5. 编辑 LeafLoom 的**现有连接**：地址后增加 `/DJ/`，账号改为 `DJ`，密码留空以保留已保存密码。连接 ID、空 `remote_root`、默认上传位置、上传目录及资料目录保持原值。也可通过带版本检查的设置 API 完成相同修改。
6. 核对旧笔记引用、分组、封面、代表性文件和目录数量。来源版本变化后允许重新扫描目录，无需下载全部原件。未执行的旧迁移计划保留，使用前重新生成，不改写旧传输记录的版本号。

验证失败时停止新容器，恢复旧客户端设置，再以原配置启动旧容器。保留所有新增内容和待传任务；两个容器不能同时占用原发布端口。

## 新增、重置或停用用户

在 **DJ 目录之外**建立独立空目录，挂载到 `/data/Alice`，配置中新增该用户自己的哈希与规则，例如 `Alice:$6$REPLACE_WITH_ALICE_SHA512_CRYPT_HASH@/Alice:rw`。保留已有挂载，重启／重建同一个容器。Alice 使用 `/Alice/` 地址及自己的密码；所有账号共用原端口。除非有意变更服务器能力，否则保留全局操作限制。

新密码通过交互式 `openssl passwd -6` 生成 SHA-512 crypt 哈希，不把密码写在命令行中。重置时只替换对应账号的哈希；停用时移除其认证规则并重启，保留文件。保持 `allow-symlink: false`；账号根目录使用真实目录或绑定挂载。
