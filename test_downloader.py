import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from downloader import (
    YouTubeAudioDownloader,
    create_master_zip,
    read_links,
    sanitize_filename,
    zip_directory,
)


class TestDownloader(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.links_file = self.test_dir / "links.txt"
        self.output_dir = self.test_dir / "output"

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("Valid Name"), "Valid Name")
        self.assertEqual(
            sanitize_filename("Name: With / Bad? * Characters!"),
            "Name With Bad Characters!",
        )
        self.assertEqual(sanitize_filename(""), "untitled")
        self.assertEqual(sanitize_filename("   "), "untitled")

    def test_read_links(self):
        content = """# Comment line
https://youtube.com/playlist?list=PL123


https://youtube.com/watch?v=abc
# Another comment
"""
        self.links_file.write_text(content)
        links = read_links(self.links_file)
        self.assertEqual(
            links,
            [
                "https://youtube.com/playlist?list=PL123",
                "https://youtube.com/watch?v=abc",
            ],
        )

    def test_zip_directory(self):
        source = self.test_dir / "source"
        source.mkdir()
        (source / "song1.mp3").write_text("dummy audio 1")
        (source / "sub").mkdir()
        (source / "sub" / "song2.mp3").write_text("dummy audio 2")

        zip_out = self.test_dir / "archive.zip"
        res = zip_directory(source, zip_out)

        self.assertIsNotNone(res)
        self.assertTrue(zip_out.exists())

        with zipfile.ZipFile(zip_out, "r") as zf:
            namelist = zf.namelist()
            self.assertIn("song1.mp3", namelist)
            self.assertIn("sub/song2.mp3", namelist)

    def test_create_master_zip(self):
        p1 = self.output_dir / "playlists" / "Playlist1"
        p2 = self.output_dir / "playlists" / "Playlist2"
        p1.mkdir(parents=True)
        p2.mkdir(parents=True)
        (p1 / "song1.mp3").write_text("audio 1")
        (p2 / "song2.mp3").write_text("audio 2")

        master_zip = self.output_dir / "youtube_audio.zip"
        res = create_master_zip(self.output_dir, master_zip, [p1, p2])

        self.assertIsNotNone(res)
        self.assertTrue(master_zip.exists())

        with zipfile.ZipFile(master_zip, "r") as zf:
            namelist = zf.namelist()
            self.assertIn(str(Path("playlists/Playlist1/song1.mp3")), namelist)
            self.assertIn(str(Path("playlists/Playlist2/song2.mp3")), namelist)

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_smart_deduplication_copy_mode(self, mock_ydl_class):
        # Set up mock yt_dlp
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        # Define behavior for download: create dummy mp3 in target cache
        def fake_download(urls):
            cache_dir = self.output_dir / ".cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            for u in urls:
                (cache_dir / "Shared Track-VID123.mp3").write_text("mp3-data")
            return 0

        mock_ydl.download.side_effect = fake_download

        downloader = YouTubeAudioDownloader(
            links_file=self.links_file,
            output_dir=self.output_dir,
            dedup_mode="copy",
        )

        p1_dir = self.output_dir / "playlists" / "PlaylistA"
        p2_dir = self.output_dir / "playlists" / "PlaylistB"

        res1 = downloader.download_single_video(
            "VID123", "https://youtube.com/watch?v=VID123", p1_dir
        )
        self.assertTrue(res1.exists())
        self.assertEqual(res1.parent, p1_dir)
        self.assertEqual(mock_ydl.download.call_count, 1)

        # Download same video in PlaylistB
        res2 = downloader.download_single_video(
            "VID123", "https://youtube.com/watch?v=VID123", p2_dir
        )
        self.assertTrue(res2.exists())
        self.assertEqual(res2.parent, p2_dir)
        # Should NOT call yt-dlp download again!
        self.assertEqual(mock_ydl.download.call_count, 1)

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_smart_deduplication_skip_mode(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        def fake_download(urls):
            cache_dir = self.output_dir / ".cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            for u in urls:
                (cache_dir / "Shared Track-VID456.mp3").write_text("mp3-data")
            return 0

        mock_ydl.download.side_effect = fake_download

        downloader = YouTubeAudioDownloader(
            links_file=self.links_file,
            output_dir=self.output_dir,
            dedup_mode="skip",
        )

        p1_dir = self.output_dir / "playlists" / "PlaylistA"
        p2_dir = self.output_dir / "playlists" / "PlaylistB"

        res1 = downloader.download_single_video(
            "VID456", "https://youtube.com/watch?v=VID456", p1_dir
        )
        self.assertIsNotNone(res1)
        self.assertTrue(res1.exists())

        # Second playlist should skip copying
        res2 = downloader.download_single_video(
            "VID456", "https://youtube.com/watch?v=VID456", p2_dir
        )
        self.assertIsNone(res2)
        self.assertFalse((p2_dir / "Shared Track-VID456.mp3").exists())


if __name__ == "__main__":
    unittest.main()
