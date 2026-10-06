# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

The local interface runs inside a Windows desktop WebView2 window. The migration engine and folder dialogs are native Python/Windows operations.

## Users and purpose

People whose existing AI development projects, profiles, caches and temporary files outgrow their main drive. They should select locations and complete setup without commands.

## Capabilities and constraints

Project names and drive letters are user choices. Known saved project records and tool folders provide fast suggestions; optional custom scans are bounded. Native parallel copying reuses unchanged files. Selected storage settings and saved paths follow the destination. Windows-managed installed software can remain on the system drive.

Original files remain in clearly identified backup locations by default. Cleanup is a separate optional operation with full content checks and an exact typed acknowledgment. The app and README recommend a separate manual backup and explain use at the user's own risk, including corruption and target-drive failure.

## Product principles

Speed, explicit folder choices, visible progress, retained originals, concise useful copy. Show decisions, paths, actual work and consequential warnings; omit idle status badges and repeated reassurance. Never force close another app. Never claim that all third-party or Windows-private writes can move.

## Confirmed visual requirements

Replace the rejected Tk interface with a modern, pleasing interface. Follow Windows light/dark preferences and provide a theme switch. Keep ordinary setup interactive and free of command instructions.

## Evidence

The repository's migration fixtures and portable Windows build checks validate copy, retention, configuration and cleanup. Synthetic performance measurements are documented as synthetic, not universal speed claims.
