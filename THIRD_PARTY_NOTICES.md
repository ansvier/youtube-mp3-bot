# Third-party notices

## Project origin and required attribution

This project is based on design patterns from **[antlis/tg-media-bot](https://github.com/antlis/tg-media-bot)**, reviewed at commit:

`01d0f07719dd7f1159a45e616419d5cf547697fd`

The upstream project is MIT-licensed. Its notice is preserved in [LICENSE](LICENSE):

> Copyright (c) 2026 antlis

Keep that copyright notice and the complete MIT permission/disclaimer text with copies or substantial portions of the software. The original attribution is intentional and must not be removed as part of privacy sanitization.

This is a specialized implementation, not a drop-in replacement, a claim of unchanged upstream files, or an assertion of upstream endorsement. Retained ideas include:

- Asynchronous aiogram routing with separate acquisition, upload, and cleanup stages.
- Argument-array yt-dlp subprocesses and per-job temporary directories.
- Global concurrency limits and per-user job admission.
- `sendAudio` with title, performer, duration, and artwork embedded in the MP3.
- UTF-8 byte-bounded filenames that preserve non-Latin text.
- Bounded retries only after explicit Telegram flood-control responses.
- `TelegramAPIServer.from_base(..., is_local=False)` for multipart uploads to a custom Bot API without a shared filesystem.

The narrower scope and security changes are described in [the historical upstream audit](docs/UPSTREAM_AUDIT.md).

## Dependencies and distributed components

Dependencies retain their own copyrights and licenses. This repository's MIT license does **not** relicense them or grant rights to downloaded media.

| Component | Source / role |
|---|---|
| aiogram | <https://github.com/aiogram/aiogram> — Telegram Bot API client and routing. |
| aiohttp | <https://github.com/aio-libs/aiohttp> — HTTP client/server transport. |
| python-dotenv | <https://github.com/theskumar/python-dotenv> — local environment-file loading. |
| yt-dlp and yt-dlp-ejs | <https://github.com/yt-dlp/yt-dlp> and <https://github.com/yt-dlp/ejs> — extraction, acquisition, and JavaScript challenge support. |
| Deno | <https://github.com/denoland/deno> — JavaScript runtime, installed through a pinned Python package distribution. |
| Mutagen | <https://github.com/quodlibet/mutagen> — MP3/ID3 metadata handling. |
| FFmpeg / ffprobe | <https://ffmpeg.org/> — codec and probing tools installed from Debian repositories. Licensing depends on the distributed build and enabled components; consult <https://ffmpeg.org/legal.html> and the package copyright notices. |
| Python and Debian base image | <https://www.python.org/> and <https://www.debian.org/> — runtime and operating-system packages with their own notices. |

`uv.lock`, `requirements.lock`, and `requirements-dev.lock` identify the Python dependency graph, including transitive and development packages. Consult the exact installed distributions and upstream license files for applicable terms; this table is not a complete software bill of materials or a substitute for those notices. Debian package copyright information is normally available under `/usr/share/doc/` inside the image.

Redistributing a built image or modified dependency can create notice, source-availability, or other obligations beyond this project's MIT notice. Review the licenses of the actual artifacts being redistributed, including FFmpeg's build configuration. Telegram and YouTube are external services with separate terms; no affiliation or endorsement is implied.
