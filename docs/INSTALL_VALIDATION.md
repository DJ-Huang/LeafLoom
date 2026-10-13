# Desktop installation acceptance

Run installation acceptance in an isolated environment. Keep user folders and credentials out of fixtures and published reports.

## Minimum checks

- First install without preinstalled runtimes; paths with spaces and non-ASCII characters.
- Download interruption, retry, checksum failure and preserved environment backups.
- Single service, normal shutdown, occupied-port reporting without stopping another app.
- Web interface and authenticated HTTP MCP; model preparation and inference verified separately.
- Login startup, tray/menu labels, icons and native launchers on the target operating system.
- Updates reuse unchanged components and load changed catalogs/web assets.

Installer regressions are in `tests/test_installer.py` and `tests/test_installer_models.py`. The manual `Desktop installer acceptance` workflow covers cold installation. Its non-desktop mode is not evidence for visible menus or login behavior.

The separate `Build LeafLoom macOS menu` workflow compiles the ARM64/macOS 14 menu with brand resources, without downloading a model. Use its artifact through the maintainer build/install process. Until a revision-4 binary is available, the launcher uses the localized system AppKit compatibility menu.

Record outcomes, skipped steps and tested revision. Windows results do not establish macOS compatibility. See [current productization validation](PRODUCTIZATION_VALIDATION.md).
