# Historical upstream design audit

## Scope and provenance

The design review used the MIT-licensed [antlis/tg-media-bot](https://github.com/antlis/tg-media-bot) at commit:

`01d0f07719dd7f1159a45e616419d5cf547697fd`

This document preserves conclusions from that historical source review, not a newly executed audit of the current upstream branch. The recorded scope included its license, README/architecture, configuration, downloader, uploader, queue, routing/handlers, cleanup, tests, and Docker startup files. File/line references below are relative to that pinned upstream tree, **not this repository**.

The review was primarily static, with limited synthetic process/path scenarios. It did not establish live Telegram or YouTube operation and was not a comprehensive independent penetration test of either project or its binary dependencies.

## Conclusion

A compact specialization fits the private, single-video YouTube-to-MP3 contract better than retaining a general multi-site video/group bot. This implementation narrows the accepted inputs and permissions while retaining useful upstream design patterns. It is not a compatible drop-in fork and does not claim upstream endorsement.

The complete MIT license and **Copyright (c) 2026 antlis** remain in [LICENSE](../LICENSE). See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for attribution and dependency boundaries.

## Patterns retained

| Upstream location | Pattern retained or adapted |
|---|---|
| `src/bot/router.py:67–73` | aiogram 3 outer middleware before handlers. |
| `src/downloaders/ytdlp.py:593–597,639–656,710–744` | Argument-array subprocess invocation, one-video handling, bounded filenames, and result metadata. |
| `src/services/uploader.py:31–49,254–277` | `sendAudio`, title/performer/duration, and bounded retry after explicit 429 responses. |
| `src/queue/manager.py:51–54` | Global processing concurrency limits. |
| `src/bot/handlers.py:422–427` | Cleanup in `finally`. |
| Custom `TelegramAPIServer` configuration | HTTP multipart upload to a custom Bot API without shared filesystem paths. |

The implementation here is specialized around those ideas; this is not a statement that upstream files were copied unchanged.

## Recorded gaps relative to this project's contract

These observations apply to the reviewed commit and the narrower requirements here. They are not claims about every upstream version or deployment.

| Area | Historical observation | Decision in this project |
|---|---|---|
| Access | Empty allowlist permitted all users; an activated group admitted its members (`router.py:43–60`). | Require nonempty `ALLOWED_USER_IDS`; serve private chats only. |
| URLs | Scheme/length validation lacked the required exact host allowlist; a pattern searched for YouTube text within a string (`ytdlp.py:234–254`). | Exact host and video-ID validation, canonicalization, and the YouTube extractor only. |
| Queue | Waiting jobs were not bounded as required here (`queue/manager.py:88–111`). | Bounded waiting queue, per-user pending/rate rules, worker slots, and container limits. |
| Process lifecycle | Termination targeted the direct PID; thumbnail FFmpeg lacked a timeout (`ytdlp.py:505–513`, `uploader.py:98–121`). | Process-group cleanup, bounded subprocess deadlines, and joined cancellation before removing files. |
| Information errors | An `asyncio.SubprocessError` reference was inappropriate for the error path (`ytdlp.py:275–298`). | Explicit stable media errors and regression tests. |
| Output contract | AUTO favored video and quality settings did not implement the required bitrate ladder (`ytdlp.py:733–762`). | Always bestaudio → MP3; measure tagged output and use 192/128/96/64 kbps cloud fallback. |
| Cleanup | Nested directories could be skipped; shutdown did not join all jobs (`cleanup.py:62–74`). | Job-owned temporary directories, joined cancellation, and ephemeral tmpfs. |
| Public errors | A friendly-error fallback could expose raw stderr (`ytdlp.py:134–146`). | Fixed English public-message maps; scrubbed diagnostics stay in logs. |
| Docker/dependencies | Root execution, loose dependency constraints, and best-effort startup upgrades. | Non-root/read-only containers, pinned Python packages with hashes, and explicit rebuilds for updates. |
| Build secrets | Broad `COPY . .` and insufficient cookie exclusions increased accidental inclusion risk. | Allowlisted build context; optional read-only cookie mount only to the worker. |
| Logging/privacy | URL, filename, and user details could become a usage history. | Avoid a link/message/username history; redact diagnostics and retain no media cache. Operational logs can still contain numeric user IDs. |
| Cache | Cache key omitted bitrate, user, and TTL (`media_cache.py:18–57`). | Remove the cache rather than expanding retention and privacy complexity. |

The historical review also noted caption truncation after `html.escape` (`uploader.py:63–68`), which could split an HTML entity. This version does not create arbitrary HTML captions. Upstream architecture prose described an `asyncio.Queue`, while the reviewed implementation used dictionaries/semaphores; decisions were based on the code rather than that description alone.

## Dependency and validation boundaries

The reviewed upstream requirements used broad lower bounds, and the startup path could update yt-dlp opportunistically. This repository uses `uv.lock` and hash-bearing requirement exports. Deno and yt-dlp-ejs are included for JavaScript support without runtime component downloads. FFmpeg comes from signed Debian repositories during builds, and the Python base image is digest-pinned.

That dependency policy is not proof of perpetual vulnerability freedom or bit-for-bit reproducibility of every future image. Inspect the actual installed versions and repeat appropriate audits when updating. Historical review results do not substitute for tests of the current revision.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the current trust and egress boundaries, and [ACCEPTANCE.md](../ACCEPTANCE.md) for the distinction between synthetic coverage, container verification, and live service proof.
