# Private YouTube → MP3 bot

Send a YouTube video link in a private Telegram chat and receive an **MP3 audio attachment** that plays in Telegram's music player. No `/audio` command is needed.

- Access is restricted to an explicit user allowlist. An empty allowlist prevents startup; groups are never served.
- Bot instructions, progress messages, and errors are in English. Video titles, artist/channel names, ID3 tags, and filenames retain Unicode, including Cyrillic; metadata is not translated.
- The worker downloads the best available audio and encodes MP3 at **192 kbps** by default. For the cloud API, oversized results are re-encoded **from the original source** at **128 → 96 → 64 kbps**, measuring the complete file after tagging each time.
- Video title, artist/uploader/channel, and measured output duration accompany the audio. Cover art is best-effort and embedded in the MP3 when available.
- One video per request: no full playlists, live streams, scheduled premieres, other sites, or group access.

Encoding at 192 kbps does not improve a lower-quality source. YouTube availability is not guaranteed: authentication requirements, service changes, and network restrictions can prevent downloads.

> Use only content you own, have permission to download, or may use under an applicable license. Also comply with YouTube and Telegram terms and applicable law. A content license, including Creative Commons, does not by itself authorize automated access to a service. This project does not bypass DRM, payment, regional restrictions, or other access controls.

## Quick start with Docker Compose

### Prerequisites

- Docker Engine or Docker Desktop running Linux containers, with **Docker Compose v2.24.4 or later**. The large-file override uses Compose's `!override` tag.
- A Linux amd64/arm64 container environment. Each architecture still requires validation on the target host.
- Network access to Telegram and YouTube/CDNs; package and image registries are also needed during builds.
- For ordinary short recordings, plan for roughly two CPU cores, at least 3 GB of available memory, and several GB of image/build storage. This is a starting point, not a capacity guarantee.
- A Telegram bot token and the positive numeric user IDs to allow.

The default deployment needs no Telegram API ID/API hash, local Bot API server, database, Redis, domain, webhook, or published network port. The host must remain running and awake.

### 1. Obtain credentials privately

Create a bot through the official [BotFather](https://t.me/BotFather) using `/newbot`. Choose your own display name and available username ending in `bot`. Store the issued token only in your local `.env` file.

Obtain your **numeric Telegram user ID**, not a username, phone number, or channel ID. For example, a [third-party ID lookup bot](https://t.me/userinfobot) can return it after `/start`; that service sees your request and public profile. It never needs your bot token.

A bot token grants control of the bot. Do not put it in issues, chats, screenshots, command-line URLs, or Git. If exposed, revoke it through BotFather and replace it locally. You may also disable group invitations in BotFather; the application rejects group use independently.

### 2. Create `.env`

Run all commands from the repository root. Preserve an existing `.env`:

```sh
test -f .env || cp .env.example .env
chmod 600 .env
nano .env
```

Fill these two deliberately blank fields locally:

```dotenv
BOT_TOKEN=
ALLOWED_USER_IDS=
```

Use comma-separated positive numeric IDs for multiple allowed users. Blank or malformed values fail closed. No real credentials or personal IDs belong in `.env.example`. Leave the other defaults unchanged for the standard cloud API setup.

### 3. Build and start

After filling `.env`:

```sh
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 bot worker
```

There are two services: **bot** handles Telegram, and **worker** handles untrusted media without receiving the Telegram token or user allowlist. No ports are published. Initial builds download dependencies.

Configuration and local dependency checks do not contact Telegram or YouTube:

```sh
docker compose run --rm --no-deps bot python -m mp3_bot --check
docker compose run --rm --no-deps worker python -m media_worker --check
```

These checks still require valid configuration. The bot check validates token format, **not token authenticity**. The worker check verifies yt-dlp, FFmpeg, ffprobe, Deno, and the MP3 encoder. Neither proves a live download or upload.

### 4. Use the bot

Open your bot in a private chat, send `/start`, then send one permitted video link as an ordinary message. Progress follows “Getting video information…” → “Downloading and converting to MP3…” → “Sending the file…” → “Done.” The result is sent through `sendAudio`, not as a document or voice message.

Only one queued or active job per user is allowed. A pending job, rate limit, full queue, or shutdown produces an English explanation rather than accepting unlimited work.

## Supported links

Accepted forms include:

- `https://youtube.com/watch?v=VIDEO_ID`
- `https://www.youtube.com/watch?v=VIDEO_ID&list=PLAYLIST_ID&t=10`
- `https://youtu.be/VIDEO_ID`
- `https://youtube.com/shorts/VIDEO_ID`
- `https://music.youtube.com/watch?v=VIDEO_ID`
- The `m.youtube.com` host and `/embed/VIDEO_ID` or `/live/VIDEO_ID` paths for completed recordings.
- Links within text or captions, and bare YouTube addresses without a scheme.

`VIDEO_ID` is a placeholder for a valid 11-character video ID, not a runnable example. Explicit schemes must be HTTP or HTTPS. Exact allowed hostnames are enforced; lookalike domains, IP addresses, credentials in URLs, and arbitrary ports are rejected.

The URL is canonicalized to one video. Playlist context, timestamps, and unrelated parameters are discarded: **the whole video is processed, not a timestamped excerpt**. A video link with a playlist parameter still means one video; a playlist-only or channel link is rejected. When several links are found, the bot announces that only the first is processed. It does not skip an invalid or non-YouTube first link to find a later valid one.

## Configuration reference

File-size settings use **decimal MB: 1 MB = 1,000,000 bytes**. Timeouts are in seconds.

| Variable | Default | Purpose |
|---|---|---|
| `BOT_TOKEN` | Blank; required | BotFather token, passed only to the bot service. |
| `ALLOWED_USER_IDS` | Blank; required | Comma-separated positive numeric user IDs; private chats only. |
| `MAX_CONCURRENT_DOWNLOADS` | `1` | Concurrent jobs. Bot slots remain occupied through upload; worker slots bound media processing. Allowed bot range: 1–32. |
| `QUEUE_SIZE` | `5` | Maximum waiting jobs, in addition to active jobs; range 1–1000. |
| `RATE_LIMIT_SECONDS` | `30` | Minimum interval between accepted requests from one user; 0 disables this interval, not the one-job-per-user rule. |
| `DOWNLOAD_TIMEOUT` | `600` | Acquisition budget. Conversion re-fetches metadata and downloads within one shared budget. The bot's preliminary information request is capped at 60 seconds. |
| `CONVERSION_TIMEOUT` | `300` | Deadline for an individual encoding/probing subprocess, not the entire job. |
| `UPLOAD_TIMEOUT` | `300` | Deadline for an individual Telegram audio upload attempt. |
| `DEFAULT_AUDIO_BITRATE` | `192` | Initial MP3 bitrate: 192, 128, 96, or 64 kbps. Cloud fallback uses only values at or below this setting. |
| `MAX_FILE_SIZE_MB` | Blank | Selects 50 for the cloud API, or 2000 for a custom/local API. May be lowered; cannot exceed the corresponding cap. |
| `MAX_SOURCE_SIZE_MB` | `512` | Maximum downloaded source size, separate from the output limit. |
| `TEMP_DIR` | `/tmp/mp3-bot` | Bot temporary directory inside its container. Keep it under writable `/tmp`. Compose fixes the worker directory to `/tmp/mp3-worker`. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `COOKIES_FILE` | Blank | Optional Netscape cookie file path **inside the worker**. No browser profile access. |
| `COOKIES_HOST_FILE` | Blank | Existing file on the Docker daemon's host; used only with `compose.cookies.yml`. |
| `TELEGRAM_API_BASE_URL` | Blank | Standard Telegram HTTPS API when blank; otherwise a trusted HTTP(S) server origin without credentials, query, fragment, or path prefix. |

`MEDIA_WORKER_URL` is an internal bot setting fixed by Compose to `http://worker:8080`. It is not an ordinary `.env` override in the supplied deployment. Outside Compose, it must point to a trusted worker; neither the worker nor this connection provides public-facing authentication.

The public Telegram cloud limit cannot be increased with a setting. A custom API hostname selects local-limit behavior in this application; **that does not establish that the server actually supports large files**. Use it only with a correctly configured, trusted local Bot API server.

## Health, resources, and lifecycle

### Readiness

The bot becomes healthy only after authentication, a successful `getUpdates`, a recent polling heartbeat, and a reachable worker. Successful `getMe` alone is insufficient. Polling success and the heartbeat must be no more than 45 seconds old; a Telegram 409 conflict clears readiness immediately. Docker's displayed health status follows its configured check interval and retries.

The worker has a separate HTTP health endpoint. It confirms HTTP responsiveness, not that YouTube is reachable or a media job will succeed. Use `--check` for local tool validation and a permitted real request for end-to-end validation.

For `telegram_poll_failed reason=conflict`, stop duplicate polling processes or resolve an existing webhook through a trusted Telegram client. The bot deliberately does **not** delete webhooks automatically.

### Default container limits

| Service | Memory cap | `/tmp` tmpfs cap | CPU quota | PID cap |
|---|---|---|---|---|
| bot | `512m` | `128m` | `1.0` | `128` |
| worker | `2g` | `1536m` | `2.0` | `128` |

Both services use UID/GID `10001:10001`, a read-only root filesystem, an init process, dropped capabilities, `no-new-privileges`, and Docker's default seccomp policy. Memory-plus-swap limits equal memory limits, requesting no container swap; confirm enforcement on the deployment host.

Tmpfs usage counts against memory. Limits are ceilings, not reservations or a promise that every allowed job fits. Source, output, optional cover copies, Python, and codec processes can coexist in memory. Increasing concurrency, source size, or output size requires coordinated RAM/tmpfs/CPU changes. A full tmpfs or an out-of-memory kill may interrupt a job.

### Logs and maintenance

```sh
docker compose logs -f --tail=100 bot worker
```

Ctrl+C stops log viewing, not the services. Logs go to stdout/stderr, with Docker rotation set to three files of 10 MB per service. No persistent log volume is required. Logs may disappear when a container is removed.

User-facing errors come from a fixed English message map, not raw tool output. Diagnostics are redacted, but logs can contain numeric user IDs and operational details; review before sharing. Do not publish `.env`, unredacted `docker inspect`, or expanded `docker compose config` output. Use `docker compose config --quiet` for syntax checks.

```sh
# Stop without removing containers.
docker compose stop
# Resume stopped services.
docker compose start
# Restart with the existing container configuration.
docker compose restart
# Apply changed .env values; restart alone does not reload them.
docker compose up -d --force-recreate
# Stop and remove this project's containers and network.
docker compose down
```

`restart: unless-stopped` restarts an exited container unless it was explicitly stopped. **An `unhealthy` status alone does not trigger Docker restart.** Investigate the cause rather than relying on health checks as a recovery service.

SIGTERM/SIGINT stops admission, cancels jobs, joins subprocess cleanup, and closes sessions. Temporary job files are cleaned after success, failure, and graceful cancellation. No Python cleanup can run after SIGKILL or power loss; container tmpfs disappears when the container stops. The queue is in memory and is not recovered after restart. Do not replace tmpfs with persistent media volumes without an explicit cleanup and retention policy.

## Optional cookies

Cookies grant access to a YouTube account session. Use them only for an account and content you are authorized to access. They do not guarantee downloads and are not a workaround for prohibited access. Never send a cookie file to the bot, upload it to Git, or install an untrusted browser extension to export it.

Supply a locally obtained **Netscape-format cookie file**. The application never reads a browser profile. See [yt-dlp's export guidance](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies); use a separate session where appropriate and revoke it if exposed.

Keep the file outside the repository and shared/synchronized folders. On a Linux Docker host, restrict it to worker UID 10001, for example with ownership assigned to that UID and mode `0400`. Docker Desktop bind-mount permissions differ; ensure the container can read it without making the file world-readable.

Set `COOKIES_HOST_FILE` in `.env` to the existing absolute path **on the Docker daemon's host**. Leave credentials and host paths out of examples committed to Git. The override mounts that file read-only and sets `COOKIES_FILE=/run/cookies/youtube.txt` inside the worker:

```sh
docker compose -f docker-compose.yml -f compose.cookies.yml up -d --build
```

Use the same `-f` options for subsequent Compose operations. Setting a path alone does not mount the file. The worker copies the jar into each private job directory because yt-dlp may update cookies; the original mount is unchanged and the copy is deleted with the job. The bot container never receives the cookie mount.

## Optional local Bot API and large files

The standard setup uses `api.telegram.org` and a 50 MB application cap. Telegram documents uploads of up to **2000 MB** through a local Bot API server.

1. Separately provision the official [Telegram Bot API server](https://github.com/tdlib/telegram-bot-api) in `--local` mode. It needs API ID/API hash credentials obtained through Telegram; those are not needed for the default deployment and do not belong in this repository.
2. Connect the bot and the server through a trusted private network with a resolvable hostname. This project does not provision the server or its network connection. Never expose an unauthenticated HTTP Bot API endpoint to the Internet: request URLs contain the bot token.
3. Stop cloud polling and follow Telegram's [migration procedure](https://core.telegram.org/bots/api#using-a-local-bot-api-server), including `logOut` on the old server before switching. Do not put token-bearing URLs in shell history or chat.
4. Set the trusted server origin in `TELEGRAM_API_BASE_URL`. Choose `MAX_FILE_SIZE_MB` and `UPLOAD_TIMEOUT` for the available capacity. For example, `MAX_FILE_SIZE_MB=2000` and `UPLOAD_TIMEOUT=1800` request the largest application limit; they are not a capacity guarantee.
5. Apply the resource override:

```sh
docker compose -f docker-compose.yml -f compose.large-files.yml up -d --build
```

The override raises bot memory to `3g` with `2200m` tmpfs, and worker memory to `6g` with `4600m` tmpfs. Provide sufficient real memory for both services **plus the host OS and the separate Bot API server**. The source cap remains 512 MB unless changed. Large jobs may need a larger source cap and longer acquisition/conversion timeouts as well as RAM.

Local API mode uses the selected starting bitrate **without cloud-style downshifting**. If the complete MP3 exceeds the configured local limit, it is rejected. Uploads use HTTP multipart (`is_local=False` in the client), not shared filesystem paths. There is no requirement to share the bot's media volume with the API server.

To combine cookies and large-file settings, specify both overrides after the base file, and reuse the same file list for later operations:

```sh
docker compose -f docker-compose.yml -f compose.cookies.yml -f compose.large-files.yml up -d --build
```

## Errors and known limits

| Situation | Expected behavior / action |
|---|---|
| Unauthorized user or group | No media processing. Unauthorized private users receive an access-denied message; group messages are ignored. |
| Invalid URL, channel, or playlist-only link | Send one supported video link. |
| Job already pending, rate-limited, queue full, or worker busy | Wait before trying again; no unbounded queue is created. |
| Private, deleted, age-restricted, region-restricted, or sign-in-required video | A safe English explanation is returned. Respect access restrictions; optional authorized cookies are not a guarantee. |
| Live or upcoming stream | Rejected; completed recordings may be supported. |
| Source or MP3 too large | Choose a shorter/smaller recording or deliberately provision the optional local-API setup. Cloud fallback stops at 64 kbps. |
| Network timeout, download, worker, or FFmpeg failure | A bounded operation fails with a safe message and cleanup. Check redacted logs and retry only when appropriate. |
| Missing or broken cover | Audio still succeeds; Telegram clients may display embedded artwork differently. |
| Telegram upload rejected | A safe upload error is returned. Only an explicit rate-limit response (429) is retried within bounded limits. |
| Upload delivery uncertain | A timeout can occur after Telegram received the file. No automatic resend is made; check the chat before requesting it again. |

YouTube may change extraction requirements, block server IPs, or refuse automated requests. There is no claim of support for every video or a guaranteed maximum duration. A successful status edit is not required to preserve a successful audio upload.

## Security and privacy boundaries

- The allowlist and private-chat check run before URL processing and job admission.
- Bot and worker use separate temporary storage and explicit environment lists. The worker has no Telegram token/user IDs, Docker socket, or host-home mount in the default deployment; the bot has no cookies.
- The worker's unauthenticated HTTP API is for a trusted dedicated container network only. Do not publish its port or attach untrusted containers.
- Subprocesses use argument arrays, not a shell. Downloader options are fixed; user text cannot provide flags or output paths. FFmpeg/ffprobe consume local files with restricted protocols/formats.
- yt-dlp configuration, plugins, caching, and remote component downloads are disabled. Deno and yt-dlp EJS support are installed from the locked dependencies.
- Exact YouTube input validation is **not a complete egress firewall** for all yt-dlp DNS, redirect, and CDN traffic. Deploy network controls separately if required. Containers are not proof against all codec or kernel vulnerabilities.
- There is no media cache or persistent job history. Telegram delivery and third-party network services have their own retention and privacy behavior.
- Ignore rules exclude local secrets and common media files, and the Docker build context is allowlisted. These are not encryption or a substitute for review. Host/Docker administrators can inspect container environments. Keep `.env` at mode `0600`, restrict Docker access, and review every file before publication.

## Local verification

The suite includes generated media, real FFmpeg/ffprobe processing, subprocess lifecycle tests, and loopback HTTP tests. External YouTube acquisition and Telegram delivery are mocked or replaced by local transports. **Passing these tests is not proof of live YouTube → Telegram delivery.** See [ACCEPTANCE.md](ACCEPTANCE.md) for evidence boundaries and a deployment checklist.

### Host checks

Install [uv](https://docs.astral.sh/uv/), Python 3.11 or later, and FFmpeg/ffprobe with `libmp3lame` support. Run on Linux or macOS; process-group tests assume POSIX. For example, install FFmpeg using `sudo apt-get install ffmpeg` on Debian/Ubuntu after updating package indexes, or `brew install ffmpeg` on macOS with Homebrew.

```sh
uv sync --frozen
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
```

Inspect skipped tests; a missing codec tool must not be mistaken for full coverage. Dependencies install during `uv sync`; tests do not require real credentials or public service access.

### Container tests without external network access

Builds require registry/package access, but the test container runs without external networking:

```sh
docker build --target test -t youtube-mp3-tests:local .
docker run --rm --init --network=none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges --memory=2g --memory-swap=2g --pids-limit=128 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=256m,mode=1777 \
  youtube-mp3-tests:local
```

`--init` is required for child-process cleanup tests. This invocation contains no host mounts or runtime credentials.

### Isolated deployment smoke

The smoke script expects these locally built image tags; no real `.env` is needed:

```sh
docker build --target bot -t private-youtube-mp3-bot:local .
docker build --target worker -t private-youtube-mp3-worker:local .
uv sync --frozen
uv run --frozen python scripts/verify_containers.py
```

It uses synthetic configuration, starts only its dedicated verification worker, checks local tools, health, token separation and Linux cgroup restrictions, deliberately crashes that verification worker, checks restart/tmpfs cleanup, then checks SIGTERM and removes its own containers. It never starts Telegram polling. Run only one copy at a time, without custom Compose overrides, and keep its reserved verification project separate from deployments. The script expects Linux cgroup v2 and the supplied default limits; platform differences may require investigation rather than weaker assertions.

For a deliberate **synthetic resource-enforcement probe**, first build the test image above, then run only in this restricted disposable container:

```sh
docker run --rm --init --network=none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges --memory=128m --memory-swap=128m \
  --pids-limit=32 --cpus=0.25 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777 \
  youtube-mp3-tests:local python scripts/probe_limits.py
```

The probe intentionally triggers a child-process OOM, process-creation denial, and CPU throttling. **Do not run the script directly on the host or inside a production container.** It tests kernel enforcement, not the maximum safe size of real media jobs.

GitHub Actions must be **manual-only**, using `workflow_dispatch`, to avoid unapproved metered runs. Do not enable automatic push/pull-request triggers without authorization. Running the local commands does not trigger a workflow, and no hosted CI result is asserted here.

## Updating

Preserve your private `.env` and any cookie file separately. Install a reviewed version of **this project**, not an upstream checkout with different access rules, then rebuild:

```sh
docker compose build --pull
docker compose up -d
docker compose logs --tail=50 bot worker
```

Reuse any enabled override files. `uv.lock` and `requirements*.lock` pin Python dependencies with hashes; no startup-time dependency upgrade is performed. For an intentional yt-dlp/EJS update, maintainers can run:

```sh
uv lock --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs
uv sync --frozen
uv export --frozen --no-dev -o requirements.lock
uv export --frozen -o requirements-dev.lock
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
docker compose build --no-cache --pull
docker compose up -d
```

Review lockfile changes and repeat container and permitted live checks. The Python base image is digest-pinned: `--pull` does not select a newer digest. Change it explicitly after review. FFmpeg comes from signed Debian repositories at build time; this is not a guarantee of the latest upstream major version or byte-identical builds across dates.

## Documentation and license

- [Acceptance and verification boundaries](ACCEPTANCE.md)
- [Architecture and security boundaries](docs/ARCHITECTURE.md)
- [Design decisions](docs/DECISIONS.md)
- [External reference sources](docs/SOURCES.md)
- [Historical upstream audit](docs/UPSTREAM_AUDIT.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md) and [MIT license](LICENSE)

Based on design patterns from [antlis/tg-media-bot](https://github.com/antlis/tg-media-bot). The upstream copyright and MIT license are preserved; this is a specialized implementation, not a drop-in replacement or an upstream-endorsed service.
