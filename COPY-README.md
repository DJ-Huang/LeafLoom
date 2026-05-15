# vault-rag 副本（`C:\Projects\vault-rag

本目录是从 **`D:\reseilion sync\UnityPackage\vault-rag`** 复制出来的 MCP 工程副本，便于在 **`C:\ExampleVault 下与其它工具集中管理。

- **Cursor MCP**：全局 `mcp.json` 里 `vault-rag` 的 `command` / `args` / `cwd` 应指向本目录（见上级或仓库内 `.cursor/mcp.json.example`）。
- **与源目录同步**：在仓库改代码后，若要让本副本一致，可在 PowerShell 执行（先关闭占用本目录 Python 的进程）：

```powershell
robocopy "D:\reseilion sync\UnityPackage\vault-rag" "C:\Projects\vault-rag" /MIR /XD __pycache__ /R:1 /W:2
```

`/MIR` 会镜像删除本副本中源已删的文件，使用前请确认无仅存在于本副本的重要文件。

- **依赖**：副本已带 `.venv` 时可直接用；若从源只拷了部分文件，在本目录执行：`pip install -e .`（在已激活的 venv 内）。
