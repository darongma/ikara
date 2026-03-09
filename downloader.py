import yt_dlp
import re
import syncedlyrics
import asyncio
import httpx
from ytmusicapi import YTMusic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from models import Song, Queue
from opencc import OpenCC
from pypinyin import pinyin, Style
from datetime import datetime

cc_to_simple = OpenCC('t2s')
cc_to_trad = OpenCC('s2t')

ytmusic = YTMusic()

def showMessage(message):
    now = datetime.now()
    formatted_now = now.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{formatted_now} : {message}")

def get_clean_message(raw_status):
    # 1. Convert object to string
    text = str(raw_status)
    
    # 2. Remove ANSI escape sequences (the \x1B colors)
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean_text = ansi_escape.sub('', text)    
    # 4. Clean up the "ERROR:" tag generally
    clean_text = clean_text.replace("ERROR: ", "").strip()
    
    return clean_text



def generate_meta_string(title: str, artist: str) -> tuple[str, str, str]:
    """
    Creates a combined searchable string containing:
    Simplified, Traditional, Pinyin, and Pinyin Shorthand.
    """
    # 1. Handle Conversions
    t_title = cc_to_trad.convert(title or "")
    s_title = cc_to_simple.convert(title or "")
    t_artist = cc_to_trad.convert(artist or "")
    s_artist = cc_to_simple.convert(artist or "")

    # 2. Generate Pinyin Data (using the Simplified title for better accuracy)
    # Style.NORMAL -> 'wo de hao xiong di'
    # Style.FIRST_LETTER -> 'w d h x d'
    p_full = pinyin(s_title+" "+s_artist, style=Style.NORMAL)
    p_short = pinyin(s_title+" "+s_artist, style=Style.FIRST_LETTER)
    
    pinyin_str = "".join([i[0] for i in p_full])
    shorthand = "".join([i[0] for i in p_short])

    # 3. Construct the Unified Meta String
    # Format: "Simplified ||| Traditional ||| Pinyin Shorthand"
    meta_text = f"{s_title} {s_artist} ||| {t_title} {t_artist} ||| {pinyin_str} {shorthand}".lower()

    return s_title, s_artist, meta_text

# --- Helper for blocking disk writes ---
def write_file_sync(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

async def search_media(query: str, search_type: str):
    if search_type == "video":
        def run_yt_search():
            ydl_opts = {'quiet': True, 'extract_flat': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(f"ytsearch20:{query}", download=False)['entries']
        
        # RUN BLOCKING SEARCH IN THREAD
        results = await asyncio.to_thread(run_yt_search)
        
        return [{
            "id": r['id'], 
            "title": r['title'], 
            "artist": r.get('uploader'), 
            "thumbnail": r.get('thumbnails')[0]['url'] if r.get('thumbnails') else "",
            "type": "video"
        } for r in results]
    else:
        # YTMusic.search is blocking, move to thread
        results = await asyncio.to_thread(ytmusic.search, query, filter="songs", limit=20)
        
        return [{
            "id": r['videoId'], 
            "title": r['title'], 
            "artist": r['artists'][0]['name'] if r.get('artists') else 'Unknown', 
            "thumbnail": r['thumbnails'][-1]['url'] if r.get('thumbnails') else "", 
            "type": "audio"
        } for r in results]

# 1. Define the semaphore at the top of downloader.py (outside the function)
# This limits the server to ONE active download/FFmpeg process at a time.
download_semaphore = asyncio.Semaphore(1)

async def download_media(db: AsyncSession, youtube_id: str, media_type: str, out_folder: str, 
                         suggested_title: str = None, suggested_artist: str = None):
    
    # Check if song already exists (do this BEFORE the semaphore so users get instant feedback)
    result = await db.execute(select(Song).where(Song.youtube_id == youtube_id))
    existing = result.scalar_one_or_none()
    if existing:
        detailed_status = f"Already in Library: {existing.title} - {existing.artist}"
        return existing, detailed_status

    # 2. Start the "Waiting Room" logic
    showMessage(f"Download request for {youtube_id} queued. Waiting for turn...")
    
    async with download_semaphore:
        # --- EVERYTHING INSIDE THIS BLOCK RUNS ONE AT A TIME ---

        # 1. Get Metadata (Blocking -> Thread)
        def fetch_info():
            ydl_opts_info = {'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                return ydl.extract_info(f"https://www.youtube.com/watch?v={youtube_id}", download=False)

        info = await asyncio.to_thread(fetch_info)
        duration = info.get('duration', 0)

        if suggested_title == "YouTube Link":
            raw_title = info.get('title', 'Unknown Title')
            raw_artist = info.get('artist') or info.get('uploader') or "Unknown Artist"
        else:
            raw_title = suggested_title or info.get('title', 'Unknown Title')
            raw_artist = suggested_artist or info.get('artist') or info.get('uploader') or "Unknown Artist"

        title = sanitize_filename(raw_title)
        artist = sanitize_filename(raw_artist)
        base_name = f"{title} - {artist} - {youtube_id}"
        ext = "mp3" if media_type == "audio" else "mp4"
        
        # 2. Download & Post-process (Very Blocking -> Thread) 
        def perform_download():
            ydl_opts = {
                'format': 'bestaudio/best' if media_type == "audio" else 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
                'outtmpl': f'{out_folder}/{base_name}.%(ext)s',
                'quiet': True,
                'noprogress': True,
            }
            if media_type == "audio":
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio', 
                    'preferredcodec': 'mp3', 
                    'preferredquality': '192'
                }]
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={youtube_id}"])

        try:
            showMessage(f"Starting actual download for: {title}")
            await asyncio.to_thread(perform_download)
            showMessage(f"{title} {artist} is downloaded to {out_folder}/{base_name}.{ext}")
        except yt_dlp.utils.DownloadError as e:
            showMessage(f"--- SERVER-SIDE ERROR REPORT ---")
            showMessage(f"Action: YouTube Download | Reason: {str(e)}")
            return None, get_clean_message(e)
        except Exception as e:
            showMessage(f"--- SERVER-SIDE SYSTEM ERROR ---")
            showMessage(f"Type: {type(e).__name__} | Message: {str(e)}")
            return None, f"System Error: {type(e).__name__}"

    # --- SEMAPHORE RELEASES HERE --- 
    # (The next person in line starts downloading now)

    # 3. Fetch Lyrics
    synced_lrc = None
    which_lyric_provider = ""
    if media_type == "audio":
        search_title = clean_query(title)
        search_artist = clean_query(artist)
        synced_lrc, which_lyric_provider = await get_lyrics_auto(search_title, search_artist, duration)
    
    if synced_lrc:
        lyrics_status = which_lyric_provider + " Lyrics Found"
    else:
        lyrics_status = "No Lyrics"

    # Combine them into a single searchable string
    s_title, s_artist, meta_text = generate_meta_string(title, artist)

    # 4. Database operations
    new_song = Song(
        title=s_title,
        artist=s_artist,
        youtube_id=youtube_id,
        file_path=f"{out_folder}/{base_name}.{ext}",
        lyrics=synced_lrc if synced_lrc else "",
        media_type=media_type,
        duration=duration,
        rank=1,
        meta=meta_text
    )
    
    db.add(new_song)
    await db.flush()
    return new_song, lyrics_status


async def get_lyrics_auto(title: str, artist: str, duration: int = 0):
    """
    Tries multiple providers to find synced lyrics.
    Returns (lyrics_text, status_message)
    """
    search_title = clean_query(title)
    search_artist = clean_query(artist)
    
    # 1. Try NetEase
    synced_lrc = await fetch_netease_lrc(search_title, search_artist)
    if synced_lrc:
        return synced_lrc, "NetEase"

    # 2. Try SyncedLyrics (lrclib/etc wrapper)
    synced_lrc = await fetch_syncedlyrics(search_title, search_artist)
    if synced_lrc:
        return synced_lrc, "SyncedLyrics"

    # 3. Try LRCLIB directly
    synced_lrc = await fetch_lrc(search_title, search_artist, duration)
    if synced_lrc:
        return synced_lrc, "LRCLIB"

    return None, "No Lyrics Found"


def clean_query(text):
    """Removes common YouTube suffixes that break lyric searches."""
    text = re.sub(r'\(.*?\)|\[.*?\]', '', text) # Remove anything in brackets/parens
    text = re.sub(r'(?i)official|video|audio|lyric|hd|4k|high res', '', text)
    return text.strip()

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

async def fetch_lrc(title, artist, duration):
    """Searches LRCLIB for synchronized lyrics."""
    url = "https://lrclib.net/api/search"
    params = {
        "track_name": title,
        "artist_name": artist,
    }
    headers = {'User-Agent': 'KaraokeSystem/1.0'}

    try:
        # Changed from requests to httpx to prevent blocking the async loop
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers, timeout=15)
            if response.status_code == 200:
                results = response.json()
                if not results:
                    return None
                
                # Find best match based on duration
                for entry in results:
                    if entry.get('syncedLyrics') and abs(entry.get('duration', 0) - duration) < 5:
                        showMessage(f"LRC found via LRCLIB for {title} {artist} {duration}")
                        return entry['syncedLyrics']
                
                # Fallback to the first result that has synced lyrics
                for entry in results:
                    if entry.get('syncedLyrics'):
                        showMessage(f"LRC found via LRCLIB for {title} {artist}")
                        return entry['syncedLyrics']
    except Exception as e:
        showMessage(f"LRCLIB Fetch Error: {e}")
    return None

async def fetch_syncedlyrics(title, artist):
    """Uses the syncedlyrics library (blocking) wrapped in a thread."""
    try:
        query = f"{title} {artist}"
        # This is correct: using to_thread for blocking libraries
        lrc = await asyncio.to_thread(syncedlyrics.search, query)
        if lrc:
            showMessage(f"LRC found via SyncedLyrics for {title} {artist}")
            return lrc
    except Exception as e:
        showMessage(f"SyncedLyrics Search Error: {e}")
    return None

async def search_netease_id(title, artist):
    """Searches NetEase for a song ID."""
    search_url = "https://music.163.com/api/search/get"
    params = {"s": f"{title} {artist}", "type": 1, "limit": 1}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(search_url, params=params, timeout=10)
            data = response.json()
            songs = data.get("result", {}).get("songs")
            if songs:
                return songs[0]["id"]
        except Exception as e:
            showMessage(f"NetEase Search Error: {e}")
    return None

async def fetch_netease_lrc(title, artist):
    """Fetches the actual LRC content using the NetEase song ID."""
    song_id = await search_netease_id(title, artist)
    if song_id:
        lrc_url = f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(lrc_url, timeout=10)
                data = response.json()
                lyric=data.get("lrc", {}).get("lyric")
                if lyric:
                    if len(lyric)>20:
                        showMessage(f"LRC found via NetEase for {title} {artist}")
                        return lyric
                    else:
                        showMessage(f"LRC {len(lyric)} found via NetEase for {title} {artist}")

            except Exception as e:
                showMessage(f"NetEase Fetch Error: {e}")
    return None



async def add_to_queue(db: AsyncSession, song_id: int, user_name: str):
    """Utility to add a song to the play queue and increment its popularity rank."""
    # 1. Fetch the song to update its rank
    result = await db.execute(select(Song).where(Song.id == song_id))
    song = result.scalar_one_or_none()
    
    if song:
        if user_name!="RANDOM": 
            song.rank = (song.rank or 0) + 1
        # No need to call db.add(song) again, SQLAlchemy tracks changes to objects in the session
    
    # 2. Create the queue entry
    new_q = Queue(song_id=song_id, user_name=user_name)
    db.add(new_q)
    
    # Flush to ensure song_id is valid and rank is updated before the route commits
    await db.flush()
    return new_q