# Design decisions

## Private, narrow scope

This is a private YouTube-to-MP3 tool, not a public multi-platform downloader. Access is fail-closed: a nonempty numeric user allowlist is required, and even allowed users are served only in private chats. Group activation, arbitrary sites, full playlists, live streams, and scheduled premieres are intentionally excluded.

Ordinary messages containing a link start the workflow; no format-selection command is required. Only the first detected link is considered so a message cannot silently create a batch of jobs. Statuses, instructions, configuration diagnostics, and public errors are English. Unicode video titles, artist names, ID3 tags, and safe filenames are preserved rather than translated or transliterated.

## Two services, one deployment

Docker Compose is the primary deployment path. Only a bot token and allowed user IDs are mandatory operator values. The worker is separated from the bot so media acquisition and codec processes do not receive Telegram credentials or user identifiers. The bot does not receive cookies.

There is no database, Redis, public administration panel, shared media filesystem, or published worker port. The internal HTTP boundary is trusted and unauthenticated; this simplifies private deployment but is not suitable for direct Internet exposure.

## Predictable audio and bounded resources

The output is always an MP3 audio attachment. The default 192 kbps bitrate is an encoding choice, not an improvement to source quality. Cloud-size fallback uses 128, 96, and 64 kbps in order, re-encoding from the original source rather than repeatedly degrading an MP3. File size is checked after tags and best-effort artwork.

The local Bot API option retains the selected bitrate instead of optimizing for the cloud cap. It requires separate trusted infrastructure and additional resources; merely changing the API hostname does not provide that infrastructure.

Per-user pending/rate checks, a bounded queue, fixed consumers, worker slots, process deadlines, source/output caps, and container resource limits prevent unbounded work. Limits can reject an otherwise valid request. Optional artwork must not cause a valid audio conversion to fail.

## Ephemeral data and conservative retries

Each service owns its temporary files. Cleanup follows success, failure, disconnect, or graceful shutdown. Bounded tmpfs handles the hard-stop case where application cleanup cannot run. There is no persistent media cache, job history, or queue recovery; this reduces retention but means interrupted jobs are not automatically resumed.

Only unambiguous Telegram flood-control responses are retried. An upload timeout can mean the file already arrived, so the bot asks the user to check the chat rather than risking a duplicate. A failed progress-message edit cannot invalidate a successful upload.

## Explicit optional credentials

Cookies are an opt-in, local Netscape-format file mounted read-only into the worker. Browser profiles are never mounted or read. A per-job copy allows yt-dlp to update its jar without changing the source file. Authorized cookies can still fail and do not authorize prohibited access.

A local Telegram Bot API is also opt-in and separately operated. It introduces additional credentials, network trust, migration steps, and memory requirements that do not belong in the default setup. The bot uploads over HTTP multipart, avoiding shared host paths.

## Reproducible dependencies, deliberate updates

Python packages are resolved through lockfiles and installed with hashes in images. The Python base image is digest-pinned. FFmpeg comes from signed Debian repositories during the build; that package source can change over time, so the whole image is not claimed to be bit-for-bit reproducible indefinitely.

Deno and EJS are installed dependencies. Runtime plugin/component downloads and automatic startup-time package upgrades are disabled. Updating dependencies is an explicit review, test, and rebuild operation, not a side effect of restarting a bot.

## Honest evidence and authorized execution

Generated audio/images, real codecs/processes, and local transports cover most behavior without involving personal accounts or external media. These checks cannot prove that a deployment's IP can access YouTube or that Telegram delivered a real file. Live validation is a separate authorized step documented in [ACCEPTANCE.md](../ACCEPTANCE.md).

Content rights and service-access permission are separate questions. A Creative Commons work is not automatic authorization for platform scraping. No test procedure requires bypassing DRM, authentication, regional restrictions, or other access controls.

GitHub Actions must remain manual-only (`workflow_dispatch`). Automated push/pull-request execution and other metered infrastructure actions require separate authorization. Complete local commands are provided so verification does not depend on authorizing hosted runs.

## Publication boundaries

Published examples leave credential and personal-ID fields blank. Local secrets, account identifiers, deployment evidence, machine-specific paths, and private host setup instructions do not belong in the public tree. Logs and generated reports require review even when the application redacts common secrets.

Upstream source attribution and the antlis copyright are licensing requirements, not personal deployment evidence. Preserve them and the full MIT notice. Dependency licenses and media/service terms remain separate obligations.
