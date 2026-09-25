# Acceptance and verification boundaries

## Evidence status

This document separates **test coverage**, **observed execution**, and **live service proof**. It is not a certificate that a particular deployment works.

The English publication candidate was freshly checked: **265 tests passed on the host and 265 passed in the restricted Linux container**, with no failures or skips. Ruff lint and formatting passed. Both production images and the test image built successfully. The isolated deployment smoke passed, including missing-allowlist rejection, worker credential separation, health, kernel restriction readback, crash recovery, temporary-file cleanup, and graceful shutdown. The runtime dependency audit reported no known vulnerabilities at verification time.

Staged content passed Gitleaks and a separate local privacy check against deployment values. The publication uses a new Git history, not the personal deployment's history. Raw logs, private configuration, launch helpers, and machine-specific evidence are excluded. These observations apply to this candidate; future changes require fresh checks.

The repository contains real production integrations with yt-dlp, FFmpeg, aiohttp, and aiogram. Test replacements are in the test suite; their success must not be reported as a real YouTube download or Telegram delivery.

| Evidence category | What is available / what remains |
|---|---|
| Source and configuration review | Implementation, tests, Compose files, lockfiles, and documented contracts can be inspected in this repository. |
| Existing synthetic regressions | 265 host tests and 265 restricted-container tests passed for the English candidate. They exercise generated media, real codecs/processes, and local HTTP transports. |
| Container build and containment | Both production targets and the test target built; the isolated deployment smoke passed. Repeat on a different deployment host. The optional reduced-resource OOM/PID/CPU stress probe was not rerun for this language-only release. |
| Hosted CI | No hosted result is asserted. GitHub Actions are to remain manual-only; a local run does not authorize a metered hosted run. |
| Live YouTube → Telegram delivery | **Not established by the published test suite or this document.** Requires a permitted source, valid private configuration, and an observed delivery from the deployment network. |
| Real cookies / local Bot API / large files | Optional configuration and algorithms have synthetic coverage, not a guarantee of a real authorized session or successful large-file deployment. |

## Acceptance matrix

The following maps requirements to implementation and test locations. Automated evidence is summarized above; live deployment checks remain a separate category.

| Requirement | Implementation and available checks |
|---|---|
| Fail-closed access, private chats only | `mp3_bot/config.py`, `mp3_bot/app.py`; `tests/test_config.py`, `tests/test_bot.py`, `tests/test_bot_entrypoint.py`. Missing/invalid allowlists prevent startup; unauthorized messages cannot start jobs. |
| English UI, Unicode metadata | Bot/public error maps, extraction and naming modules; bot, error, naming, encoding, and integration tests. Instructions and errors are English; titles and artist names are not translated or transliterated. |
| YouTube only; one video; first link policy | `media_worker/urls.py`, `tests/test_urls.py`. Canonicalization removes playlist/time context; pure playlists and arbitrary hosts are rejected. |
| No live or upcoming streams | `media_worker/extraction.py`, `tests/test_media_extraction.py`. |
| Bounded work admission | Bot queue, per-user pending/rate checks, and worker semaphore; `tests/test_bot.py`, `tests/test_media_pipeline.py`. |
| MP3 bitrate fallback from original source | `media_worker/encoding.py`, `tests/test_media_encoding.py`. Generated audio exercises complete tagged file-size boundaries and 192 → 128 → 96 → 64 kbps fallback. |
| Local API without cloud downshift | Media/configuration and bot entrypoint tests. Local mode keeps the selected bitrate and rejects oversized output. |
| Accurate title, performer, duration, and audio attachment | `tests/test_integration.py`, `tests/test_bot_client.py`, `tests/test_bot_contract.py`, `tests/test_bot_http.py`. Actual MP3 duration is probed; `SendAudio` metadata and multipart bytes are checked using local transports. |
| Best-effort artwork | Encoding, pipeline, and thumbnail tests cover bounded image retrieval and copy-before-tagging. Artwork failure must not invalidate clean audio. |
| No successful truncated fragment download | `tests/test_media_fragments.py` uses real yt-dlp with locally generated HLS; missing tail fragments must fail and clean up. |
| Safe subprocess and path handling | `media_worker/process.py`, `tests/test_process.py`. Fixed argv, restricted child environment, output/disk/deadline bounds, process-group termination, and cancellation cleanup. |
| Cleanup after success, error, disconnect, and shutdown | Pipeline, process, service, and bot lifecycle tests; dedicated container smoke verifies tmpfs loss on container restart. |
| Safe errors and diagnostic redaction | Error maps, `mp3_bot/logging.py`, worker diagnostics; logging, media diagnostics, service, and bot failure tests. Logs still need privacy review before sharing. |
| Correct handling of Telegram uncertainty | `tests/test_bot_failures.py`. Retry only explicit bounded 429 responses, not ambiguous upload transport failures; status-edit failure must not discard delivered audio. |
| Readiness based on polling | Health, polling, and lifecycle tests. Authentication alone is insufficient; successful recent `getUpdates` and worker reachability are required. A conflict removes readiness. |
| Cookies isolated to worker | Per-job copied cookie jar, read-only optional mount, and synthetic cookie tests. No browser profile access or Telegram-side cookie upload. |
| Container limits and recovery | Compose plus `scripts/verify_containers.py` and `scripts/probe_limits.py`. Configured limits are not proof of kernel enforcement until run on the target host. |
| Attribution and publication hygiene | `LICENSE`, `THIRD_PARTY_NOTICES.md`, and `docs/UPSTREAM_AUDIT.md`; separately inspect the actual publication tree for secrets and personal evidence. |

### What the integration tests really do

`tests/test_integration.py` connects a generated WAV source to real encoding, the real worker HTTP service, the real bot client, the dispatcher, and `SendAudio`. Source acquisition and the Telegram session are synthetic. It checks Unicode metadata and removal of temporary files.

`tests/test_bot_http.py` checks actual multipart request construction against a loopback Telegram-like endpoint. That endpoint is not Telegram. `tests/test_media_fragments.py` uses real yt-dlp, but replaces external acquisition with a local HLS fixture generated from a test tone. Neither fixture authorizes or proves downloading real platform content.

Codec tests can be skipped if tools are missing. Review skips explicitly; a passing run with missing FFmpeg coverage is not equivalent to the complete container suite.

## Reproduce local checks

Use the complete commands in [README: Local verification](README.md#local-verification):

1. Install host prerequisites, sync frozen dependencies, run pytest, Ruff lint, and Ruff format checks.
2. Build the Docker test target and run the suite with no external network, a read-only root, `--init`, and bounded resources.
3. Build both production targets, then run the isolated deployment smoke. It checks startup without real Telegram credentials, missing-allowlist rejection, worker tools/health, secret separation, cgroup/security settings, forced application-crash recovery, tmpfs cleanup, and SIGTERM.
4. Optionally run the reduced-resource probe **only in the restricted disposable container**. It intentionally triggers child OOM, PID exhaustion, and CPU throttling; never run it in production or directly on a host.

Builds and dependency installation need external package access; test cases use generated media and mocks/loopback transports. Container smoke/probes require a compatible Linux Docker environment and cgroup v2. Do not weaken assertions merely to make an unsupported environment report success.

Record the exact revision, commands, exit statuses, skipped tests, relevant tool versions, and any sanitized result files in a private verification record. Do not publish token values, user/chat IDs, cookie data, local absolute paths, host identifiers, or raw container inspections. A security/dependency scan is time-specific and is not a permanent warranty.

## Live deployment checklist

These checks are a separate, authorized operation; do not infer their completion from automated tests.

- [ ] Obtain your bot token and allowlisted numeric user IDs privately; leave committed placeholders blank.
- [ ] Confirm a lawful source and permission for the intended automated access. Use a short recording you are entitled to process.
- [ ] Validate Compose syntax and both `--check` modes, then start the deployment.
- [ ] Observe worker readiness and bot health after real authentication and successful polling. Resolve duplicate pollers/webhooks rather than ignoring 409 conflicts.
- [ ] In an allowlisted private chat, send one link and observe English progress/error text.
- [ ] Receive a playable MP3 **audio** attachment, with expected title/performer and measured duration. Check Unicode metadata when applicable; artwork is optional.
- [ ] Confirm disallowed private users cannot process media and groups are not served, using only accounts/chats you are authorized to test.
- [ ] Confirm temporary job data is removed and operational logs do not expose secrets. Do not publish raw evidence containing personal IDs or URLs.
- [ ] If using cookies, verify the read-only worker-only mount and authorized session separately.
- [ ] If using a local Bot API, verify migration, private connectivity, capacity, and actual large-file delivery separately. Cloud-mode tests do not cover that server.

YouTube can refuse requests despite correct code, cookies, or a current extractor. The project does not promise access to every video, support for every hosting network, end-to-end anonymity, or complete protection from kernel/codec vulnerabilities. See [architecture](docs/ARCHITECTURE.md) and [reference sources](docs/SOURCES.md).
