#!/usr/bin/env python3
"""
Automated YouTube Audio Downloader
Downloads YouTube videos/playlists from links.txt as high-quality MP3s,
organizes them per playlist / single tracks with smart anti-duplication,
and archives them into zip files (per playlist + master zip).
"""

import argparse
import logging
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("yt_audio_downloader")


def sanitize_filename(name: str, max_length: int = 150) -> str:
    """Sanitize string to be safe for directory and file names."""
    if not name:
        return "untitled"
    # Replace characters that are invalid in filenames
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = "untitled"
    return cleaned[:max_length]


def read_links(file_path: Path) -> List[str]:
    """Read non-empty, non-comment lines from links file."""
    if not file_path.exists():
        logger.warning(f"Links file {file_path} not found.")
        return []
    links = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            cleaned = line.strip()
            if cleaned and not cleaned.startswith("#"):
                links.append(cleaned)
    return links


def build_yt_dlp_options(
    output_template: str,
    audio_format: str = "mp3",
    audio_quality: str = "0",  # "0" = best VBR / 320k
    download_archive_file: Optional[Path] = None,
) -> dict:
    """Build configuration options dictionary for yt-dlp."""
    postprocessors = [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_format,
            "preferredquality": audio_quality,
        },
        {"key": "FFmpegMetadata", "add_metadata": True},
    ]

    opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": postprocessors,
        "quiet": False,
        "no_warnings": False,
        "ignoreerrors": True,
        "extract_flat": False,
    }

    if download_archive_file:
        opts["download_archive"] = str(download_archive_file)

    return opts


def zip_directory(source_dir: Path, output_zip_path: Path) -> Optional[Path]:
    """Compress contents of source_dir into output_zip_path."""
    if not source_dir.exists() or not any(source_dir.iterdir()):
        logger.warning(f"Directory {source_dir} is empty or missing. Skipping zip.")
        return None

    output_zip_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Creating zip archive: {output_zip_path}")

    with zipfile.ZipFile(
        output_zip_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as zipf:
        for root, _, files in os.walk(source_dir):
            for file in files:
                file_path = Path(root) / file
                # Do not zip zip files if they are in the directory
                if file_path.suffix.lower() == ".zip":
                    continue
                arcname = file_path.relative_to(source_dir)
                zipf.write(file_path, arcname)

    logger.info(
        f"Zip created successfully: {output_zip_path} ({os.path.getsize(output_zip_path)} bytes)"
    )
    return output_zip_path


def create_master_zip(
    output_dir: Path, master_zip_path: Path, playlist_dirs: List[Path]
) -> Optional[Path]:
    """
    Compress all downloaded audio files across all playlist directories into
    a single master zip archive (e.g. youtube_audio.zip).
    """
    master_zip_path.parent.mkdir(parents=True, exist_ok=True)
    has_files = False

    with zipfile.ZipFile(
        master_zip_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as zipf:
        for p_dir in playlist_dirs:
            if not p_dir.exists():
                continue
            for root, _, files in os.walk(p_dir):
                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix.lower() == ".zip":
                        continue
                    arcname = file_path.relative_to(output_dir)
                    zipf.write(file_path, arcname)
                    has_files = True

    if has_files:
        logger.info(
            f"Master zip created: {master_zip_path} ({os.path.getsize(master_zip_path)} bytes)"
        )
        return master_zip_path
    else:
        logger.warning("No audio files found to add to master zip archive.")
        if master_zip_path.exists():
            master_zip_path.unlink()
        return None


class YouTubeAudioDownloader:
    def __init__(
        self,
        links_file: Path = Path("links.txt"),
        output_dir: Path = Path("output"),
        audio_quality: str = "0",  # "0" (best) or "320"
        dedup_mode: str = "copy",  # "copy", "skip", or "hardlink"
        download_archive: Optional[Path] = None,
    ):
        """
        :param links_file: Path to text file containing links
        :param output_dir: Directory where downloads and zip files will be stored
        :param audio_quality: MP3 quality (0 = highest VBR, or 320 for CBR)
        :param dedup_mode:
            - 'copy': Download audio once globally into a cache pool, copy into each playlist directory.
            - 'skip': If a track has already been downloaded into an earlier playlist, skip subsequent playlists.
            - 'hardlink': Hardlink the cached audio into each playlist directory (saves disk space).
        :param download_archive: File to persist yt-dlp download history.
        """
        self.links_file = Path(links_file)
        self.output_dir = Path(output_dir)
        self.audio_quality = audio_quality
        self.dedup_mode = dedup_mode
        self.shared_cache_dir = self.output_dir / ".cache"
        self.archive_file = (
            Path(download_archive)
            if download_archive
            else self.output_dir / "downloaded_archive.txt"
        )

        # In-memory tracking of processed YouTube video IDs: video_id -> path to mp3 in cache
        self.downloaded_video_cache: Dict[str, Path] = {}
        # Track which videos have been added to which target directories
        self.placed_videos: Dict[str, Set[Path]] = {}

    def extract_entry_info(self, url: str) -> Optional[dict]:
        """Extract metadata without downloading."""
        if yt_dlp is None:
            raise RuntimeError(
                "yt-dlp is not installed. Run 'pip install yt-dlp'."
            )
        flat_opts = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
        }
        with yt_dlp.YoutubeDL(flat_opts) as ydl:
            return ydl.extract_info(url, download=False)

    def download_single_video(
        self, video_id: str, video_url: str, target_dir: Path
    ) -> Optional[Path]:
        """
        Downloads a single video audio directly to cache if not already downloaded,
        then places it in target_dir using dedup_mode.
        Returns the path to the MP3 in target_dir.
        """
        self.shared_cache_dir.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=True)

        # Check if already downloaded in this session
        cached_file = self.downloaded_video_cache.get(video_id)
        if cached_file and cached_file.exists():
            logger.info(
                f"[Anti-Duplicate] Video {video_id} already downloaded. Applying mode '{self.dedup_mode}'."
            )
            return self._handle_duplicate_track(video_id, cached_file, target_dir)

        # Check if already present in shared_cache_dir on disk
        existing_matches = list(self.shared_cache_dir.glob(f"*{video_id}*.mp3"))
        if existing_matches and existing_matches[0].exists():
            cached_file = existing_matches[0]
            self.downloaded_video_cache[video_id] = cached_file
            logger.info(
                f"[Anti-Duplicate] Found existing file in cache for {video_id}: {cached_file.name}."
            )
            return self._handle_duplicate_track(video_id, cached_file, target_dir)

        # Download into shared_cache_dir
        cache_template = str(
            self.shared_cache_dir / "%(title).100s-%(id)s.%(ext)s"
        )
        ydl_opts = build_yt_dlp_options(
            cache_template,
            audio_format="mp3",
            audio_quality=self.audio_quality,
            download_archive_file=self.archive_file,
        )

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ret_code = ydl.download([video_url])

        # Find the newly downloaded MP3
        found_files = list(self.shared_cache_dir.glob(f"*{video_id}*.mp3"))
        if not found_files:
            logger.warning(
                f"Failed to find converted MP3 for video {video_id} ({video_url})"
            )
            return None

        cached_file = found_files[0]
        self.downloaded_video_cache[video_id] = cached_file

        return self._handle_duplicate_track(video_id, cached_file, target_dir)

    def _handle_duplicate_track(
        self, video_id: str, cached_file: Path, target_dir: Path
    ) -> Optional[Path]:
        """Handles placing or skipping a cached track in target_dir."""
        dest_file = target_dir / cached_file.name
        placed_dirs = self.placed_videos.setdefault(video_id, set())

        if dest_file.exists():
            placed_dirs.add(target_dir)
            return dest_file

        if self.dedup_mode == "skip" and len(placed_dirs) > 0 and target_dir not in placed_dirs:
            # Already placed in another directory
            logger.info(
                f"[Skip Mode] Skipping {cached_file.name} in {target_dir.name} (already placed in another playlist)."
            )
            return None

        if self.dedup_mode == "hardlink":
            try:
                os.link(cached_file, dest_file)
                placed_dirs.add(target_dir)
                logger.info(
                    f"Hardlinked {cached_file.name} -> {target_dir.name}"
                )
                return dest_file
            except Exception as e:
                logger.warning(
                    f"Hardlink failed ({e}), falling back to copy."
                )

        # Default: 'copy'
        shutil.copy2(cached_file, dest_file)
        placed_dirs.add(target_dir)
        logger.info(f"Copied {cached_file.name} -> {target_dir.name}")
        return dest_file

    def process_url(
        self, url: str
    ) -> Tuple[Optional[str], Optional[Path], Optional[Path]]:
        """
        Process a single URL (playlist or individual video).
        Returns (collection_title, collection_dir, collection_zip_path).
        """
        logger.info(f"Processing URL: {url}")
        try:
            info = self.extract_entry_info(url)
        except Exception as e:
            logger.error(f"Error fetching info for {url}: {e}")
            return None, None, None

        if not info:
            logger.error(f"No info extracted for URL: {url}")
            return None, None, None

        is_playlist = "entries" in info
        title = info.get("title") or ("Playlist" if is_playlist else "Track")
        safe_title = sanitize_filename(title)

        if is_playlist:
            collection_dir = self.output_dir / "playlists" / safe_title
            collection_zip = (
                self.output_dir / "zips" / f"playlist_{safe_title}.zip"
            )
        else:
            collection_dir = self.output_dir / "single_tracks"
            collection_zip = (
                self.output_dir / "zips" / f"track_{safe_title}.zip"
            )

        collection_dir.mkdir(parents=True, exist_ok=True)

        if is_playlist:
            entries = list(info.get("entries") or [])
            total_entries = len(entries)
            logger.info(
                f"Playlist '{title}' contains {total_entries} candidate entries."
            )
            for idx, entry in enumerate(entries, 1):
                if not entry:
                    continue
                v_id = entry.get("id")
                v_url = (
                    entry.get("url")
                    or entry.get("webpage_url")
                    or f"https://www.youtube.com/watch?v={v_id}"
                )
                v_title = entry.get("title", f"Track {idx}")
                logger.info(
                    f"[{idx}/{total_entries}] Processing: {v_title} ({v_id})"
                )
                try:
                    self.download_single_video(v_id, v_url, collection_dir)
                except Exception as e:
                    logger.error(f"Error downloading {v_id} ({v_url}): {e}")
        else:
            v_id = info.get("id")
            v_url = info.get("webpage_url") or url
            logger.info(f"Downloading single track: {title} ({v_id})")
            try:
                self.download_single_video(v_id, v_url, collection_dir)
            except Exception as e:
                logger.error(f"Error downloading {v_id} ({v_url}): {e}")

        # Create per-collection zip file
        zip_path = None
        if any(collection_dir.iterdir()):
            zip_path = zip_directory(collection_dir, collection_zip)

        return title, collection_dir, zip_path

    def run(self) -> List[Path]:
        """
        Execute full download workflow.
        Returns list of all created zip archives.
        """
        links = read_links(self.links_file)
        if not links:
            logger.warning(f"No links found in {self.links_file}.")
            return []

        logger.info(
            f"Found {len(links)} link(s) to process from {self.links_file}."
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.archive_file.parent.mkdir(parents=True, exist_ok=True)

        created_zips: List[Path] = []
        playlist_dirs: List[Path] = []

        for url in links:
            title, p_dir, p_zip = self.process_url(url)
            if p_dir and p_dir not in playlist_dirs:
                playlist_dirs.append(p_dir)
            if p_zip and p_zip not in created_zips:
                created_zips.append(p_zip)

        # Create the master zip file containing all files (youtube_audio.zip)
        master_zip = self.output_dir / "youtube_audio.zip"
        if playlist_dirs:
            master = create_master_zip(self.output_dir, master_zip, playlist_dirs)
            if master:
                created_zips.append(master)

        logger.info(f"Completed! Generated {len(created_zips)} zip archive(s):")
        for z in created_zips:
            logger.info(f" - {z.name} ({os.path.getsize(z)} bytes)")

        return created_zips


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Download YouTube videos and playlists as high-quality MP3s and organize them into zip archives."
    )
    parser.add_argument(
        "--links-file",
        type=Path,
        default=Path("links.txt"),
        help="Path to file containing YouTube URLs (default: links.txt)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Path to output root directory (default: output)",
    )
    parser.add_argument(
        "--audio-quality",
        type=str,
        default="0",
        help="Audio quality for MP3 extraction (0 is best VBR, or 320 for CBR, default: 0)",
    )
    parser.add_argument(
        "--dedup-mode",
        choices=["copy", "skip", "hardlink"],
        default="copy",
        help=(
            "Smart deduplication mode across playlists:\n"
            "  'copy': Download once globally, copy to each playlist folder (playlists stay self-contained).\n"
            "  'skip': Download once globally, omit from subsequent playlists.\n"
            "  'hardlink': Download once globally, hardlink in each playlist folder (saves disk space)."
        ),
    )
    parser.add_argument(
        "--archive-file",
        type=Path,
        default=None,
        help="Path to download archive file to prevent re-downloading previously processed tracks.",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    downloader = YouTubeAudioDownloader(
        links_file=args.links_file,
        output_dir=args.output_dir,
        audio_quality=args.audio_quality,
        dedup_mode=args.dedup_mode,
        download_archive=args.archive_file,
    )
    downloader.run()


if __name__ == "__main__":
    main()
