# YouTube Audio Downloader

Automated Python-based YouTube audio downloader using `yt-dlp` and `ffmpeg`. Extracts high-quality MP3s from YouTube playlists or individual videos, deduplicates tracks across playlists, and packages them into per-playlist `.zip` archives and a master `youtube_audio.zip`.

## Features
- **High-Quality Audio Extraction:** Uses `yt-dlp` and `ffmpeg` to extract the best quality audio streams and convert them to MP3 with ID3 metadata tags.
- **Playlist & Single Video Support:** Reads URLs directly from `links.txt`.
- **Smart Anti-Duplication:** Detects tracks present in multiple playlists. Tracks are downloaded only once from YouTube into a shared cache.
  - Dedup modes supported via `--dedup-mode`:
    - `copy` (default): Audio is downloaded once and placed in each playlist folder so each playlist archive is completely self-contained.
    - `skip`: Audio is downloaded once for the first playlist it appears in, and omitted from subsequent playlists.
    - `hardlink`: Audio is downloaded once and hardlinked across playlists to minimize disk usage.
- **Automatic Archiving:**
  - Creates individual `.zip` files for each playlist under `output/zips/playlist_<name>.zip`.
  - Creates a consolidated `output/youtube_audio.zip` containing all downloaded songs organized by folder.
- **GitHub Actions Automation:**
  - Manual dispatch workflow `.github/workflows/download.yml` runs in GitHub Actions and uploads the zip archives as downloadable artifacts.

## Usage

### 1. Add Links
Add your playlist or video links to `links.txt` (one per line):
```text
https://youtube.com/playlist?list=PLiy0XOfUv4hERj0kPVUjAqFHE4tI8UTbW&si=_5PjgPP6BO-pXOPq
https://youtube.com/playlist?list=PLUxj-5SZJmi0&si=IfdCHKCW5hBBDII_
https://youtube.com/playlist?list=PLX4VMYCYO1Q8DX7s_FeGOxlChML6t5u_8&si=jPdTdNha8_VTboFv
https://youtube.com/playlist?list=PLK3LTcBIURgg&si=GUHTJ-rLmn7H7jjp
https://youtube.com/playlist?list=PLdfMdsz2WKbQ&si=pELl2NBikhU_l8it
https://youtube.com/playlist?list=PLc4ekoKdCk1E&si=DsB1R1uWuegoVqM1
https://youtube.com/playlist?list=PLo4oBUR4qEJObQc-6GAytZ0P-n4F1e3rR&si=4XUJ_yq9FgYYIo_v
```

### 2. Local Installation & Execution
```bash
# Install dependencies
pip install -r requirements.txt
sudo apt-get install -y ffmpeg # on Debian/Ubuntu, or brew install ffmpeg on macOS

# Run downloader
python downloader.py
```

Optional flags:
```bash
python downloader.py \
  --links-file links.txt \
  --output-dir output \
  --dedup-mode copy \
  --audio-quality 0
```

### 3. Run via GitHub Actions
Go to **Actions** -> **Download YouTube Audio** -> **Run workflow**. Choose your deduplication mode and audio quality. When completed, download `youtube_audio_all` or `playlist_archives` from the Artifacts section.
