# 🎤 iKARA uOK

A self-hosted karaoke server for your local network — runs on Windows, streams to any device with a browser.

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-☕-yellow?style=for-the-badge&logo=paypal)](https://paypal.me/darongma)

![iKARA uOK](static/karaoke.png)

---

## What makes iKARA uOK different

Most karaoke apps play a static background or loop one clip. iKARA uOK does something different:

- **Your own videos play behind the lyrics.** Point the app at any folder of MP4/MKV/MOV/AVI files and they become the live background on the karaoke stage. Got a folder of concert footage, travel videos, or music videos? They all work.
- **Portrait and landscape videos are handled automatically.** The app uses `ffprobe` to detect each video's actual dimensions (including rotation metadata from phone-shot videos) and routes portrait videos to portrait screens, landscape to landscape — no manual sorting required.
- **Timed lyrics are fetched automatically.** When a song is downloaded, the app queries three providers in sequence (NetEase → SyncedLyrics → LRCLIB) and attaches the best synced `.lrc` it finds. Lyrics scroll in sync with the music on the stage screen.
- **Full Chinese language support.** Song search and the library work across Simplified Chinese, Traditional Chinese, Pinyin full text, and Pinyin shorthand simultaneously — so you can find `小蘋果` by typing `xiao ping guo`, `xpg`, or just `apple`.

---

## Features

| Feature | Details |
|---|---|
| 🔍 YouTube Music search | Search and download audio tracks with one tap |
| 🎬 YouTube video download | Download music videos to use as karaoke tracks |
| 📂 Personal video backgrounds | Use your own local video files as the stage background |
| 🎵 Auto lyrics | Synced LRC lyrics fetched automatically on download |
| 📱 Multi-device | Host screen on TV, remote control from any phone on the LAN |
| 📋 Queue management | Drag-and-drop reorder, clear, or skip songs |
| 🔀 Random queue | Fill the queue with random songs from your library |
| 🌐 Multi-language UI | English and Traditional/Simplified Chinese |
| 📊 QR code join | Guests scan a QR code to join from their phone |
| 💻 System info | Live CPU, memory, disk, and library stats |

---

## Requirements

- **Python 3.11+**
- **ffmpeg / ffprobe** — required for video orientation detection  
  Download from [ffmpeg.org](https://ffmpeg.org/download.html) and make sure `ffprobe` is on your system PATH
- A modern browser (Chrome / Edge recommended for the host/stage screen)

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/darongma/ikara.git
cd ikara

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Create your config file (copy the example and edit it)
copy config.example.json config.json
```

Edit `config.json` to point to your folders:

```json
{
    "db_folder": "C:\\KALAOK",
    "media_folder": "C:\\KALAOK\\DOWNLOAD",
    "bg_video_folder": [
        "C:\\Videos\\Music",
        "D:\\Videos\\Travel"
    ],
    "default_volume": 80,
    "language": "en",
    "no_cache": false,
    "port": 5555
}
```

| Key | Description |
|---|---|
| `db_folder` | Where `karaoke.db` and `videos.db` are stored |
| `media_folder` | Where downloaded songs and videos are saved |
| `bg_video_folder` | One or more folders of background video files. Orientation is auto-detected — just throw everything in |
| `default_volume` | Playback volume on startup (0–100) |
| `language` | UI language: `"en"` or `"zh"` |
| `no_cache` | Set `true` during development to disable CSS/JS caching |
| `port` | Port the server listens on |

```bash
# 4. Start the server
python main.py
```

The stage screen opens automatically in Microsoft Edge in app mode. On any other device on your network, open a browser and go to `http://<server-ip>:<port>`.

---

## How it works

```
┌─────────────────────────────────────────────────────┐
│                    LAN Network                       │
│                                                      │
│  📺 Host / Stage Screen        📱 Guest Phones       │
│  (TV or monitor)                                     │
│  /host                         /  (remote)           │
│                                /search               │
│         ↕ WebSocket (Socket.IO) ↕                    │
│                                                      │
│            🖥  iKARA Server (Python)                 │
│            FastAPI + SQLite + yt-dlp                 │
└─────────────────────────────────────────────────────┘
```

- The **host screen** (`/host`) is the stage — it plays the song, shows scrolling lyrics, and displays the background video. Open this on your TV or main monitor.
- **Guests** connect from their phones and use the remote (`/`), search (`/search`), queue (`/queue`), or library (`/library`) pages.
- All screens stay in sync in real time via Socket.IO.

### Video background system

On startup, iKARA scans every file in `bg_video_folder`, runs `ffprobe` to read the video dimensions, accounts for rotation metadata, and stores the results in `videos.db`. Portrait videos (height > width) and landscape videos are kept in separate shuffle queues. Each video plays exactly once before the cycle repeats — so if you have 30 videos and 30 songs, every video gets shown once.

### Lyrics pipeline

When a song is downloaded, the app searches for synced `.lrc` lyrics in this order:

1. **NetEase Music** — best coverage for Chinese songs
2. **SyncedLyrics** (lrclib wrapper) — broad Western coverage  
3. **LRCLIB** — direct API fallback with duration-based matching

If no synced lyrics are found the song is still added to the queue; you can paste lyrics manually from the library editor.

---

## Project structure

```
iKara-OK/
├── main.py            # FastAPI app, all routes, Socket.IO events
├── downloader.py      # yt-dlp wrapper, lyrics fetching, search
├── videodb.py         # ffprobe scanning, video orientation DB
├── database.py        # SQLAlchemy async engine setup
├── models.py          # Song and Queue ORM models
├── config.py          # Config loading, validation, splash screen
├── systeminfo.py      # CPU/disk/memory stats
├── migrate.py         # DB migration helpers
├── translations.json  # UI strings (English + Chinese)
├── requirements.txt
├── static/            # CSS, JS, icon
└── templates/         # Jinja2 HTML templates
    ├── base.html      # Shared nav, modals, Socket.IO bootstrap
    ├── host.html      # Stage / karaoke screen
    ├── search.html    # YouTube search + download
    ├── library.html   # Song library + editor
    ├── queue.html     # Queue management
    └── welcome.html   # Remote control / landing page
```

---

## API reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/search?q=&type=` | Search YouTube (`video`) or YouTube Music (`audio`) |
| POST | `/api/download` | Download a YouTube video or audio track |
| GET | `/api/library` | List all songs in the library |
| PUT | `/api/library/{id}` | Edit song title, artist, or lyrics |
| DELETE | `/api/library/{id}` | Delete a song and its file |
| GET | `/api/queue` | Get the current queue |
| POST | `/api/queue/reorder` | Reorder the queue |
| DELETE | `/api/queue/{id}` | Remove one item from the queue |
| DELETE | `/api/queue/clear` | Clear the queue (keeps currently playing song) |
| POST | `/api/queue/finished/{id}` | Mark a song as finished and remove it |
| POST | `/api/queue/random/{count}` | Add N random songs to the queue |
| GET | `/api/host/current` | Get the currently playing song |
| GET | `/api/host/next` | Advance to the next song |
| GET | `/api/random_background?orientation=` | Get a background video URL |
| POST | `/api/rescan_videos` | Re-scan video folders and rebuild the video DB |
| GET | `/api/video_stats` | Get video DB counts by orientation |
| GET | `/api/system/info` | System stats (CPU, memory, disk, library sizes) |
| GET | `/qrcode` | QR code image pointing to the server |

---

## Socket.IO events

| Event | Direction | Description |
|---|---|---|
| `request_song` | client → server | Add a library song to the queue |
| `media_control` | client → server | `toggle` / `restart` / `next` |
| `volume_control` | client → server | Set volume level |
| `refresh_queue` | server → client | Queue has changed, reload UI |
| `refresh_library` | server → client | Library has changed, reload UI |
| `host_command` | server → client | Forward media control to host screen |
| `host_volume` | server → client | Set volume on host screen |

---

## Credits

Developer: **Darong Ma 馬達榮**  
Email: darongma@yahoo.com
Website: https://www.darongma.com

If you enjoy iKARA uOK, consider buying me a coffee! ☕  
👉 [paypal.me/darongma](https://paypal.me/darongma)

---

## License

MIT