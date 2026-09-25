# External reference sources

These are primary references for the project's design and operational limits, not a claim that every external page was rechecked for this publication. Service limits, requirements, and terms can change; review the current source before deployment or an upgrade. Installed versions are defined by the repository's lockfiles and the resulting image, not by a static documentation version list.

| Topic | Reference | How it applies |
|---|---|---|
| Telegram audio messages and file uploads | [Bot API: sendAudio](https://core.telegram.org/bots/api#sendaudio), [Sending files](https://core.telegram.org/bots/api#sending-files) | MP3 audio attachments and the cloud upload policy. The application enforces a 50 decimal MB cloud cap. |
| Local Bot API operation and migration | [Using a local Bot API server](https://core.telegram.org/bots/api#using-a-local-bot-api-server), [official server](https://github.com/tdlib/telegram-bot-api) | The documented local upload limit is 2000 MB. Operators must separately provision the server, protect token-bearing traffic, and follow migration requirements. |
| Bot creation and token management | [BotFather](https://t.me/BotFather), [Telegram bot features](https://core.telegram.org/bots/features#botfather) | Bot registration and credential management; no real credential belongs in this repository. |
| yt-dlp options and releases | [yt-dlp repository](https://github.com/yt-dlp/yt-dlp), [releases](https://github.com/yt-dlp/yt-dlp/releases) | Extractor behavior changes over time. Update through the lockfiles and tests, not an uncontrolled startup-time upgrade. |
| YouTube JavaScript support | [yt-dlp EJS setup](https://github.com/yt-dlp/yt-dlp/wiki/EJS) | Deno and yt-dlp-ejs are installed dependencies for modern YouTube extraction; remote component downloads are disabled by this project. |
| Cookie handling | [yt-dlp: exporting YouTube cookies](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies) | Guidance for authorized local cookie files. A session file is sensitive and does not guarantee access. |
| YouTube usage restrictions | [YouTube Terms of Service](https://www.youtube.com/static?template=terms) | Permissions for content use, downloading, and automated service access are distinct. Consult applicable current terms; a content license is not a blanket scraping permission. |
| Compose overrides | [Docker Compose merge rules](https://docs.docker.com/reference/compose-file/merge/) | The large-file override replaces tmpfs entries using `!override`; the documented project prerequisite is Compose v2.24.4+. |
| FFmpeg distribution licensing | [FFmpeg legal guidance](https://ffmpeg.org/legal.html) | The applicable license depends on the actual build and bundled components; image redistribution needs its own review. |
| Upstream source and MIT license | [antlis/tg-media-bot](https://github.com/antlis/tg-media-bot/tree/01d0f07719dd7f1159a45e616419d5cf547697fd) | Attribution and the historical design review are pinned to this commit, not to the latest upstream branch. |

This project uses decimal MB for application file limits; Docker resource quantities are preserved as written in Compose. No external reference guarantees that a given source can be downloaded from a given network, or that a particular host can process the largest configured file. Those are separate live acceptance checks.
