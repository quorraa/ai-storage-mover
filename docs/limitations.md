# Limits and recovery

This release migrates explicitly selected regular files, directories and links. It does not migrate Windows Store registration, services, installed desktop binaries automatically, Windows private package data, registry hives, ACL ownership, alternate data streams, EFS metadata, sparse allocation, or original hardlink topology. Use a supported vendor/Windows installer for applications requiring these properties. Profiles should be moved only to a private, access-controlled destination. The run directory contains private path metadata and verification evidence; do not commit it.

The source is authoritative. Destination-only files stay in place; conflicting destination entries move to the run's `conflicts` archive. This preserves unique clone content but does not perform application-specific merges of stale history databases. Review pre-existing destination profiles before activating them.

Stop writers before cutover. Rename probes release themselves on ordinary failure, and their journaled identity permits restoring a probe after interruption. The copy worker rejects changes noticed during file copying, and cutover checks the source snapshot before moving it. Metadata fingerprints do not detect a malicious actor preserving inode, size and timestamp; full adversarial filesystem isolation is outside scope.

Source files are preserved until `retire` is explicitly invoked with the plan ID. Cleanup checks the source pointer, destination volume, exact backup identity, manifest and current destination presence. It deletes only recorded backup entries in depth order. It refuses unexpected source content. After retirement begins rollback is unavailable; the destination remains the authoritative copy.

For partial cutover use `apply --apps-closed` with the original, unchanged plan. For partial cleanup use `retire --confirm ORIGINAL_ID`. Never create a replacement plan to delete orphaned roots. Inspect the journal and preserve both copies if a writer recreated a source or a manual edit changed a pointer.

Runtime settings affect processes started with them. Already-running apps, Windows services, Task Scheduler actions and sandbox brokers can choose a different environment. Windows package/sandbox temp directories may remain on C:. Project-relative build outputs follow the project location; tools with hardcoded absolute paths need explicit configuration. Verify tool-reported locations and a real write before claiming a workload uses the storage drive.

Windows and Linux fixture coverage is configured in CI; only locally executed checks should be reported as passed. GitHub CI does not test real installed MSIX apps or application updater behavior. The included package activation helper has been exercised with registered desktop apps on Windows; that does not guarantee every vendor/version's storage settings.
