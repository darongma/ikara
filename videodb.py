"""
videodb.py — Background video metadata cache.

On startup, scans all configured bg_video_folder paths, runs ffprobe on any
new or modified files, and stores results in <db_folder>/videos.db (SQLite).

The rest of the app calls:
    await video_db.get_random(orientation="landscape")  →  file path or None
    await video_db.rescan()                             →  rescans all folders
"""

import os
import json
import sqlite3
import random
import asyncio
import subprocess
from datetime import datetime
from downloader import showMessage

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_VIDEO_EXTS = ('.mp4', '.mkv', '.mov', '.avi')


def _open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            file_path   TEXT PRIMARY KEY,
            width       INTEGER,
            height      INTEGER,
            orientation TEXT,
            duration    REAL,
            codec       TEXT,
            fps         REAL,
            file_size   INTEGER,
            date_scanned TEXT
        )
    """)
    conn.commit()
    return conn


def _probe_file(file_path: str) -> dict | None:
    """
    Runs ffprobe on a single file and returns a dict of metadata.
    Returns None if ffprobe fails or the file has no video stream.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        file_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None

    # Find the first video stream
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        None
    )
    if not video_stream:
        return None

    width  = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))

    # Account for rotation metadata (common in phone-shot portrait videos)
    rotation = 0
    tags = video_stream.get("tags", {})
    if "rotate" in tags:
        try:
            rotation = abs(int(tags["rotate"]))
        except ValueError:
            pass
    # Also check side_data_list for display matrix rotation
    for sd in video_stream.get("side_data_list", []):
        if sd.get("side_data_type") == "Display Matrix":
            try:
                rotation = abs(int(sd.get("rotation", 0)))
            except (ValueError, TypeError):
                pass

    # Swap dimensions if rotated 90° or 270°
    if rotation in (90, 270):
        width, height = height, width

    if width == 0 or height == 0:
        return None

    orientation = "portrait" if height > width else "landscape"

    # Duration: prefer format-level, fall back to stream-level
    duration = 0.0
    try:
        duration = float(data.get("format", {}).get("duration", 0))
    except (ValueError, TypeError):
        try:
            duration = float(video_stream.get("duration", 0))
        except (ValueError, TypeError):
            pass

    # FPS from avg_frame_rate "30/1" or "30000/1001"
    fps = 0.0
    try:
        num, den = video_stream.get("avg_frame_rate", "0/1").split("/")
        if float(den) > 0:
            fps = round(float(num) / float(den), 2)
    except (ValueError, ZeroDivisionError):
        pass

    codec    = video_stream.get("codec_name", "unknown")
    file_size = os.path.getsize(file_path)

    return {
        "file_path":   file_path,
        "width":       width,
        "height":      height,
        "orientation": orientation,
        "duration":    round(duration, 2),
        "codec":       codec,
        "fps":         fps,
        "file_size":   file_size,
        "date_scanned": datetime.utcnow().isoformat(),
    }


def _scan_sync(db_path: str, folders: list[str]) -> dict:
    """
    Blocking scan — meant to be called via asyncio.to_thread().

    Strategy:
    - Collect every video file currently on disk across all folders.
    - Remove DB rows whose file no longer exists on disk.
    - Probe only files that are new (not in DB) or whose size has changed.
    - Return counts: { new, updated, removed, total, landscape, portrait }
    """
    conn = _open_db(db_path)

    # Map of path → file_size for everything currently on disk
    disk_files: dict[str, int] = {}
    for folder in folders:
        if not os.path.exists(folder):
            showMessage(f"VideoDB: Folder not found, skipping: {folder}")
            continue
        for fname in os.listdir(folder):
            if fname.lower().endswith(_VIDEO_EXTS):
                fp = os.path.join(folder, fname)
                try:
                    disk_files[fp] = os.path.getsize(fp)
                except OSError:
                    pass

    # Pull existing DB rows
    existing = {
        row["file_path"]: row["file_size"]
        for row in conn.execute("SELECT file_path, file_size FROM videos").fetchall()
    }

    # Remove stale rows
    stale = [p for p in existing if p not in disk_files]
    if stale:
        conn.executemany("DELETE FROM videos WHERE file_path = ?", [(p,) for p in stale])
        conn.commit()
        showMessage(f"VideoDB: Removed {len(stale)} stale entries.")

    # Probe new or changed files
    to_probe = [
        p for p, size in disk_files.items()
        if p not in existing or existing[p] != size
    ]

    new_count     = 0
    updated_count = 0
    failed_count  = 0

    for fp in to_probe:
        showMessage(f"VideoDB: Probing → {os.path.basename(fp)}")
        meta = _probe_file(fp)
        if meta is None:
            showMessage(f"VideoDB: ffprobe failed for {os.path.basename(fp)}, skipping.")
            failed_count += 1
            continue

        is_new = fp not in existing
        conn.execute("""
            INSERT OR REPLACE INTO videos
                (file_path, width, height, orientation, duration,
                 codec, fps, file_size, date_scanned)
            VALUES
                (:file_path, :width, :height, :orientation, :duration,
                 :codec, :fps, :file_size, :date_scanned)
        """, meta)

        if is_new:
            new_count += 1
        else:
            updated_count += 1

    conn.commit()

    # Final counts per orientation
    rows = conn.execute(
        "SELECT orientation, COUNT(*) as cnt FROM videos GROUP BY orientation"
    ).fetchall()
    counts = {r["orientation"]: r["cnt"] for r in rows}

    total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    conn.close()

    showMessage(
        f"VideoDB: Scan complete — "
        f"{new_count} new, {updated_count} updated, "
        f"{len(stale)} removed, {failed_count} failed. "
        f"Total: {total} "
        f"(landscape: {counts.get('landscape', 0)}, portrait: {counts.get('portrait', 0)})"
    )

    return {
        "new": new_count,
        "updated": updated_count,
        "removed": len(stale),
        "failed": failed_count,
        "total": total,
        "landscape": counts.get("landscape", 0),
        "portrait":  counts.get("portrait", 0),
    }


def _load_queue_sync(db_path: str, orientation: str) -> list[str]:
    """
    Loads all video paths of the given orientation from the DB,
    shuffles them, and returns the list.
    """
    conn = _open_db(db_path)
    rows = conn.execute(
        "SELECT file_path FROM videos WHERE orientation = ?", (orientation,)
    ).fetchall()
    conn.close()
    paths = [r["file_path"] for r in rows]
    random.shuffle(paths)
    return paths


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

class VideoDatabase:
    """
    Async wrapper around the SQLite helpers with shuffle-then-drain queues.

    Two in-memory queues (landscape + portrait) are loaded from the DB and
    shuffled once. Each call to get_random() pops from the front of the
    relevant queue. When a queue runs dry it reloads and reshuffles from the
    DB, guaranteeing every video is shown exactly once per cycle before any
    repeats.

    The queues are rebuilt automatically after every rescan() so newly added
    or removed videos are reflected immediately.
    """

    def __init__(self, db_path: str, folders: list[str]):
        self.db_path = db_path
        self.folders = folders
        self._queues: dict[str, list[str]] = {"landscape": [], "portrait": []}
        self._lock = asyncio.Lock()

    async def _refill(self, orientation: str) -> None:
        """Reload + reshuffle a queue from the DB."""
        paths = await asyncio.to_thread(_load_queue_sync, self.db_path, orientation)
        self._queues[orientation] = paths
        showMessage(
            f"VideoDB: Queue refilled -- {len(paths)} {orientation} videos ready."
        )

    async def rescan(self) -> dict:
        """Scan all folders, probe new/changed files, update DB, rebuild queues."""
        stats = await asyncio.to_thread(_scan_sync, self.db_path, self.folders)
        # Rebuild both queues so new/removed videos take effect immediately
        async with self._lock:
            await self._refill("landscape")
            await self._refill("portrait")
        return stats

    async def get_random(self, orientation: str = "landscape") -> str | None:
        """
        Pop the next video from the shuffle-then-drain queue for this orientation.
        Refills and reshuffles when the queue runs dry.
        Falls back to the opposite orientation, then to any video if truly empty.
        """
        async with self._lock:
            for attempt in range(2):
                orient = orientation if attempt == 0 else (
                    "portrait" if orientation == "landscape" else "landscape"
                )

                if not self._queues[orient]:
                    await self._refill(orient)

                if self._queues[orient]:
                    path = self._queues[orient].pop(0)
                    if attempt > 0:
                        showMessage(
                            f"VideoDB: No {orientation} videos found, "
                            f"falling back to {orient}."
                        )
                    return path

        # Absolute last resort -- should only happen if DB is completely empty
        showMessage("VideoDB: No videos found in DB at all.")
        return None

    async def get_stats(self) -> dict:
        """Return current DB counts without rescanning."""
        def _stats(db_path):
            conn = _open_db(db_path)
            total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            rows  = conn.execute(
                "SELECT orientation, COUNT(*) as cnt FROM videos GROUP BY orientation"
            ).fetchall()
            conn.close()
            counts = {r["orientation"]: r["cnt"] for r in rows}
            return {
                "total":     total,
                "landscape": counts.get("landscape", 0),
                "portrait":  counts.get("portrait", 0),
            }
        return await asyncio.to_thread(_stats, self.db_path)


def check_ffprobe() -> bool:
    """
    Returns True if ffprobe is available on PATH.
    Call this at startup; refuse to start if it returns False.
    """
    try:
        subprocess.run(
            ["ffprobe", "-version"],
            capture_output=True,
            timeout=5
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False