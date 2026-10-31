# One DUFS container, separate attachment accounts

[English](DUFS_MULTIUSER.md) · [中文](../zh-CN/DUFS_MULTIUSER.md) · [日本語](../ja/DUFS_MULTIUSER.md)

Each account gets its own directory, originals and metadata. For example, DJ connects to `https://files.example.com/DJ/`, and Alice to `https://files.example.com/Alice/`. Each person uses their own LeafLoom installation and credentials. Account administration is through the server configuration; there is no self-registration.

## Build and verify the server

Upstream DUFS 0.47.0 rejects links outside the global server root, but permits links between account directories inside that root. Use the patched image, with `allow-symlink: false`, before adding independent users. The patch rejects symbolic links and linked parent directories, hides them from listings/search/archives and checks COPY/MOVE destinations. This also disables links within the same account. Local NAS administrators and filesystem writers remain trusted; this is not a sandbox against a hostile local process racing filesystem changes.

From the repository root, on an ARM64 Docker host:

```sh
docker build --platform linux/arm64 -t leafloom/dufs:0.47.0-symlink1 templates/dufs
python3 scripts/check_dufs_isolation.py --docker-image leafloom/dufs:0.47.0-symlink1
docker image save --platform linux/arm64 -o dufs-symlink1-arm64.tar leafloom/dufs:0.47.0-symlink1
```

Use `linux/amd64` for an x86-64 NAS. The Dockerfile pins the upstream source checksum, builder image and Cargo lockfile. `--version` identifies the patch as `0.47.0-leafloom.1`. The test uses disposable accounts/files and a random loopback port; it never contacts the user's NAS. OpenSSL is required to create its fictional password hashes. A nonzero test exit blocks deployment.

## Preserve DJ's existing content

Copy [the server configuration](../../templates/dufs/config.yaml.example) outside the served data tree. Replace the placeholder with the **existing complete SHA-512 crypt password hash**, without changing the password. Retain existing global operation settings. In this deployment the originals stay read-only, with uploads and metadata writable under `Incoming`:

```yaml
auth:
  - 'DJ:$6$REPLACE_WITH_EXISTING_SHA512_CRYPT_HASH@/DJ:ro,/DJ/Incoming:rw'
allow-symlink: false
```

Adapt [the Compose template](../../templates/dufs/compose.yaml.example). Bind the existing attachment directory to `/data/DJ:ro`, its existing `Incoming` directory to `/data/DJ/Incoming:rw`, and the private configuration directory to `/config:ro`. No originals are copied or moved. Do not grant `/` to an account or add an anonymous rule. Keep passwords, hashes, private paths and recovery backups out of Git.

## Apply through Zspace Docker

1. Back up the current container configuration, DUFS configuration and LeafLoom attachment workspace. Record mount access modes separately: a Zspace YAML export may omit read-only flags. Retain the old image and configuration.
2. Upload the tested image archive and the new configuration/Compose file to the NAS configuration directory. In **Docker → Images → Import → Import from Zspace**, import the archive.
3. Quit LeafLoom after saving drafts. Confirm there are no active uploads or metadata writes; preserve staged originals and pending records. Stop the old attachment container and disable its automatic startup to prevent a port conflict after reboot.
4. Import the prepared Compose project using the patched image. Keep the original published port, network, resource limits and mount access modes. Only one attachment-service container should be running. The stopped old container can remain as a rollback copy.
5. Edit the existing LeafLoom server connection: append `/DJ/` to its base address and change the username to `DJ`; leave the saved password untouched. Keep the storage ID, empty `remote_root`, default destination, upload directory and metadata directory. A version-checked settings API update can make the same change.
6. Verify old note references, groups, covers, representative files and catalog counts. A changed source revision restarts directory discovery without requiring all originals to be downloaded. Retain unused migration plans and recreate them before execution; do not rewrite old transfer-journal revisions.

If verification fails, stop the new container, restore the previous client settings and restart the original container with its original configuration. Preserve all newly created data and pending uploads. Do not run both containers on the same published port.

## Add, reset or disable an account

Create a new, empty NAS directory **outside DJ's tree**, mount it at `/data/Alice`, then add a separate hash and rule, such as `Alice:$6$REPLACE_WITH_ALICE_SHA512_CRYPT_HASH@/Alice:rw`. Restart/recreate the same container with all existing mounts retained. Alice connects to `/Alice/` with their own password. The same port serves every account. Preserve the global operation restrictions unless deliberately changing the server's capabilities.

Create new SHA-512 crypt hashes with an interactive `openssl passwd -6` prompt; do not put passwords on command lines. To reset a password, replace only that account's hash. To disable an account, remove its authentication rule and restart the container, retaining its files. Keep `allow-symlink: false`; account roots must be real directories or bind mounts.
