# PR106 — Plugin Trust Model

## Security status

Atlas plugins are **trusted in-process Python code**. The plugin SDK provides
integrity pinning, admission policy, and deterministic quarantine diagnostics.
It does **not** provide a sandbox or contain malicious code after import.

Operators must not load a plugin merely because Atlas reports that its digest
matches. Trust means “this bundle matches a locally approved SHA-256 value,”
not “this code is safe.”

## What Atlas enforces

Enforcement is opt-in:

- `PluginDiscovery(require_trust=True, trust_store=...)` requires an exact
  plugin-id, version, and bundle-digest record.
- Bundle hashing covers the normalized manifest and files under the selected
  plugin root. Explicit include paths cannot escape the root; file symbolic
  links are rejected.
- `PluginPermissionPolicy` rejects a manifest when a requested permission is
  denied or not granted. Explicit deny rules take precedence.
- `PluginRuntime(permission_policy=...)` repeats the manifest permission gate
  before resolving and calling extension factories.
- Invalid, duplicate, tampered, untrusted, or policy-denied discoveries receive
  deterministic `plugin-quarantined` diagnostics.

Without `require_trust=True`, an untrusted plugin may be discovered. Without a
permission policy, requested permissions do not prevent runtime loading. These
defaults preserve PR59 compatibility and are not secure-mode defaults.

## What Atlas does not enforce

- No process, container, interpreter, filesystem, network, or syscall sandbox.
- No runtime interception of file, network, subprocess, environment, import,
  reflection, or native-extension access.
- No least-privilege capability objects. Manifest permissions are an admission
  gate, not capability enforcement after code starts.
- No cryptographic publisher signatures, certificate chain, transparency log,
  revocation service, or remote reputation check. `PluginTrustRecord.signer`
  is unauthenticated operator metadata.
- No protected trust-store storage or operating-system ACL management.
- No automatic re-hash immediately before Python import. A bundle modified
  after discovery but before runtime load creates a time-of-check/time-of-use
  risk unless the operator makes the bundle immutable.
- No confidentiality guarantee for values placed in `PluginContext`; plugins
  can retain or transmit services and data they receive.
- No denial-of-service containment for CPU, memory, threads, disk, or shutdown
  behavior.

## Threat model

The controls address accidental changes, storage tampering detected before
admission, dependency duplication, malformed manifests, and centralized
operator allow/deny policy. They assume the Atlas process, Python environment,
trust-store administrator, and approved plugin code are trusted.

They do not defend the Atlas process from a malicious or compromised approved
plugin, a compromised Python dependency, an attacker who can alter both a
bundle and its trust store, or mutation after verification.

## Recommended production deployment

1. Review plugin source and dependencies; build a fixed, read-only artifact.
2. Calculate the digest in the deployment environment and approve it through a
   separately controlled trust-store workflow.
3. Always set `require_trust=True` and supply an explicit deny-by-default
   `PluginPermissionPolicy` to both discovery and runtime.
4. Keep plugin roots and the trust store read-only for the Atlas service
   account. Do not colocate untrusted writable files in a hashed plugin root.
5. Run Atlas in an OS-level sandbox, container, VM, or restricted service
   account when plugin compromise is in scope. Apply network egress controls,
   filesystem mounts, resource limits, and secret isolation outside Atlas.
6. Restart from immutable artifacts for upgrades; do not mutate a verified
   bundle in place.
7. Treat plugin exceptions, health events, and structured logs as detection
   signals, not containment.

## Future hardening

Potential future controls include signed provenance, protected trust-store
updates, re-verification at load time, isolated worker processes, explicit
capability brokers, resource limits, and dependency vulnerability policy.
None of these are claimed by PR106.
