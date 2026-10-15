# Tunnel integration validation — 2026-10-15

Implemented for Windows x64 and macOS 14+ Apple Silicon. The official
`tunnel-client-runtime` is pinned to v0.0.16; archive and license-report SHA256
values are in `scripts/tunnel-runtime.json`.

## Observed on Windows

- Eight focused Python tests passed: loopback initialization/list/call without
  a token; Host/Origin rejection; peer-address enforcement despite spoofed
  forwarding headers; existing bearer compatibility; browser CSRF and independent
  AI-session authentication; runtime restart/stop and failure isolation.
- These tests also ran the actual bundled Windows runtime against a local mock
  control plane. It became ready and polled successfully without real credentials
  or external requests, despite absent OAuth discovery metadata.
- Nine Node checks passed, including encrypted-storage wiring, redacted status,
  restart restoration, unavailable encryption, corrupt configuration, and the
  existing desktop boundary/lifecycle checks.
- A native Electron smoke verified actual Windows system encryption/decryption,
  the private sidecar pipe, a successful unauthenticated MCP status call,
  missing-runtime failure isolation, and service cleanup on quit.
- Packaged-app UI acceptance passed: save encrypted credentials with connection
  disabled, clear the password input, restore after restart, clear configuration,
  retain service when closing to tray, and quit. All data was disposable; no real
  user credentials, knowledge folders, or remote calls were used.
- Frontend production build and source whitespace/syntax checks passed. Both
  Windows and macOS runtime downloads and license reports matched their pinned
  digests. The Windows runtime's version command reported v0.0.16.

## Remaining external acceptance

- macOS runtime execution, UI, Keychain, signing, notarization, and Gatekeeper
  require a native Mac. The desktop CI includes native and packaged-app checks
  for both platforms; that CI was not dispatched from this Windows session.
- A real OpenAI control-plane connection and ChatGPT web tool call require the
  user's runtime App Key, Tunnel/workspace association, and first-time plugin
  setup. Neither is claimed by local mock readiness. Enter the key in the app,
  select the same Tunnel in ChatGPT with No authentication, then call
  `vault_index_status` to complete end-to-end acceptance.

The change does not migrate knowledge data or rotate the existing local MCP
token. Previously installed versions continue using their existing code until
the updated application is installed and restarted.
