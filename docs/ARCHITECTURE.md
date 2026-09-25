# Architecture and security boundaries

One Python repository provides two Compose services. There is no database, Redis, webhook receiver, public HTTP dashboard, or persistent media cache.

```text
Telegram long polling → bot (aiogram)
  → mandatory user allowlist + private-chat gate
  → first-link extraction and strict YouTube URL canonicalization
  → per-user rate/pending checks + bounded queue + fixed consumers
  → worker POST /info (preliminary information)
  → worker POST /convert (authoritative result)
      → private per-job temporary directory
      → re-extract metadata + download one bestaudio source with yt-dlp
      → best-effort bounded cover retrieval
      → FFmpeg MP3 + ID3 title/artist/artwork
      → measure complete file; cloud fallback from ORIGINAL source
      → ffprobe final output duration
      → stream MP3 + bounded metadata → worker cleanup
  → bot-local temporary MP3 → Telegram sendAudio → bot cleanup
```

## Responsibilities and internal protocol

**Bot:** authenticate to Telegram; authorize users; admit bounded work; send English statuses/errors; validate worker replies; upload audio; report polling readiness. It receives the bot token and user IDs, but not the cookie file.

**Worker:** validate URLs again; fetch media; run codec tools; tag and measure output; stream it to the bot. Its supplied Compose environment contains neither the Telegram token nor the allowlist. It is an unauthenticated internal service, not a public API.

The HTTP contract is intentionally narrow:

- `GET /health` returns `{"status":"ok"}`. It checks service responsiveness, not upstream availability or a real encoding job.
- `POST /info` and `POST /convert` accept only a JSON object with the `url` field; query parameters and extra keys are rejected. Request bodies are limited to 4096 bytes.
- `/info` returns preliminary title, performer, and optional duration.
- `/convert` re-extracts information instead of accepting client-supplied paths, options, or metadata. The result is `audio/mpeg` with a content length and a bounded, URL-safe base64 JSON `X-Media-Info` header. JSON retains Unicode.
- The bot validates metadata structure, bounds the received bytes independently, and does not follow worker redirects. No filesystem paths are shared between services.
- Errors use stable codes and safe messages. The bot selects its own public message by code instead of trusting arbitrary worker text. A failed stream is closed rather than acquiring a JSON error suffix.

Final title/performer/duration come from `/convert`, not its preliminary `/info` result. Video title takes priority over a music-track label; artist falls back to uploader/channel. Metadata is normalized and bounded, not translated. Filenames strip unsafe path characters and are bounded by UTF-8 bytes.

## Media policy

Inputs are restricted to exact supported YouTube hostnames and a valid 11-character video ID. Canonicalization removes playlist context, tracking parameters, and start timestamps. Playlist-only/channel links and live/upcoming media are rejected; an eligible completed `/live/` recording is still one video.

The downloader uses fixed argument arrays, the YouTube extractor, `bestaudio`, the native downloader, one fragment at a time, and `--abort-on-unavailable-fragments`. It ignores ambient yt-dlp configuration and disables plugins, cache files, and remote component fetching. Deno and EJS are installed with the locked dependencies, rather than downloaded during a request. The downloader is not permitted to delegate to FFmpeg; the encoder owns FFmpeg invocation.

FFmpeg and ffprobe consume local files with `file,pipe` protocol and format restrictions. The encoder maps audio only, strips inherited metadata, writes title/artist tags, then measures the complete MP3 after optional artwork. Cloud mode tries **192 → 128 → 96 → 64 kbps**, starting at the configured bitrate and always reusing the original source. Custom/local API mode uses only the selected bitrate. Both reject output over their configured byte cap.

Cover retrieval is optional, HTTPS-only, restricted to supported YouTube image hosts/paths, without redirects, and capped at 2,000,000 bytes. A bounded fetch or embedding failure leaves audio usable. Artwork is first applied to a disposable MP3 copy; only a successfully probed result replaces the clean file. Telegram client artwork presentation is outside the application's control.

## Work, deadlines, and lifecycle

Bot admission checks and queue insertion occur without an intervening await. A user can have only one queued or active job. Accepted-request timestamps implement the rate limit; a fixed consumer pool bounds concurrency through upload, and a bounded queue caps waiting work. The worker has a separate semaphore and rejects excess work instead of building a second unbounded queue.

The preliminary bot information call is capped at 60 seconds. A conversion's metadata extraction and source download share the download budget. Encoding/probing subprocesses have individual conversion deadlines; a fallback can require several operations. The worker client allocates a bounded overall conversion request budget, and the worker limits response streaming to 300 seconds. Raising `UPLOAD_TIMEOUT` changes Telegram upload behavior, not all internal deadlines.

Each job owns its directory and optional copy of the cookie jar. Subprocesses receive an explicit non-secret environment, start in a process group, and have bounded stdout/stderr plus disk watchdogs. Timeout or cancellation terminates the group and joins cleanup before deleting its directory. Docker's init process reaps orphaned descendants.

SIGTERM/SIGINT stops work and cancels active tasks; graceful cleanup removes job data and closes sessions. Nothing makes `finally` execute after SIGKILL or power loss. Separate container tmpfs mounts therefore provide ephemeral storage; no durable queue or automatic job recovery is implemented. An interrupted request may need to be sent again.

## Deployment isolation and resource limits

The default Compose deployment has:

- Non-root UID/GID `10001:10001`, read-only root filesystems, all capabilities dropped, `no-new-privileges`, and Docker's default seccomp policy.
- No published service ports, host-home mount, Docker socket, or shared media volume.
- Separate bounded `/tmp` tmpfs mounts, memory/CPU/PID limits, and memory-plus-swap limits equal to memory caps.
- Explicit environment lists rather than forwarding the whole `.env` into both services.
- An optional read-only cookie-file bind mount to the worker only; yt-dlp modifies a per-job copy, not the mounted original.

See [README](../README.md#health-resources-and-lifecycle) for exact default caps and the large-file override. Tmpfs memory and codec/process memory compete under the same container memory cap. Configuration maxima are not guarantees that every combination fits. Resource enforcement must be checked on the actual host.

The Compose network is a **trusted container network with outbound connectivity**, not an egress-isolated sandbox. Do not publish the worker port or attach untrusted containers. Exact input-host validation does not prove complete SSRF protection across every yt-dlp DNS lookup, redirect, or CDN request. Stronger deployments need a separately designed egress firewall. Container restrictions also do not eliminate all decoder or kernel attack surfaces.

The optional local Telegram Bot API is a separately operated trusted service. Multipart uploads use `is_local=False`; it does not need access to the bot's media paths. A custom hostname selects the application's local-file-size policy, but the operator must establish that the remote server really is an appropriately configured local Bot API.

## Readiness, logs, and delivery semantics

Bot health requires authentication, a recent successful `getUpdates`, a fresh event-loop heartbeat, and a reachable worker. Both heartbeat and polling timestamps must be within 45 seconds. A 409 conflict clears readiness immediately; Docker's visible status changes on its check schedule. A successful `getMe` or a startup marker alone is not readiness. The worker's HTTP check does not validate YouTube access.

`restart: unless-stopped` recovers an exited service; Docker does not automatically restart a merely unhealthy container. The queue and tmpfs media are not restored. Health recovery is not proof that an interrupted user job completed.

Logs go to stdout/stderr with Docker rotation of three 10 MB files per service. Redaction suppresses token-bearing URLs and credential-like data; worker diagnostics use bounded/scrubbed output. Numeric user IDs may appear in bot diagnostics. Logs are operational data, not guaranteed anonymous output: review before sharing and do not retain them unnecessarily.

Public messages are English and selected from a fixed error map. Unicode source metadata remains intact within the sanitization bounds. The bot does not maintain a link/message/username history or media cache, but Telegram and upstream services have separate retention policies.

Only explicit Telegram 429 responses receive bounded retries: at most three upload attempts, with retry waits accepted only in the 0–60 second range. A transport timeout may happen **after** Telegram accepts an upload, so ambiguous delivery is reported without automatic resend. A status-message edit failure after successful `sendAudio` does not turn that success into an upload failure.
