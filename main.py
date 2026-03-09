import os
import qrcode
import socket
import uvicorn
from io import BytesIO
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Query, HTTPException, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from socketio import AsyncServer, ASGIApp
from datetime import datetime, timedelta, timezone
from database import init_db, async_session, engine
from downloader import search_media, download_media, add_to_queue, generate_meta_string, get_lyrics_auto, showMessage
from sqlalchemy import select, delete, update
from models import Song, Queue
from systeminfo import get_system_stats
from sqlalchemy.sql.expression import func
from fastapi import Response
import mimetypes
import config
from videodb import VideoDatabase, check_ffprobe


import time
import threading
import subprocess
import requests
import aiofiles
import asyncio

# In-memory lock set: tracks queue_ids currently being processed.
# Prevents multiple browser tabs from both "winning" the finish_song race
# when DELETE ... RETURNING is not available in aiosqlite/SQLite.
_finishing_lock = asyncio.Lock()
_finished_ids: set = set()

# Lifespan handles DB initialization and directory checks
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- ffprobe check: refuse to start if not installed ---
    if not check_ffprobe():
        showMessage("=" * 60)
        showMessage("FATAL: ffprobe not found on PATH.")
        showMessage("ffprobe is required for automatic video orientation detection.")
        showMessage("Install it via: https://ffmpeg.org/download.html")
        showMessage("Make sure ffprobe is accessible from the command line.")
        showMessage("=" * 60)
        raise RuntimeError("ffprobe is not installed. Cannot start iKARA.")

    await init_db()
    if not os.path.exists(config.MEDIA_FOLDER):
        os.makedirs(config.MEDIA_FOLDER)

    # --- Init video DB and scan on startup ---
    video_db_path = os.path.join(config.DB_FOLDER, "videos.db")
    app.state.video_db = VideoDatabase(video_db_path, config.BG_VIDEO_FOLDER)
    showMessage("VideoDB: Starting background video scan...")
    await app.state.video_db.rescan()

    yield

app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if not getattr(config, "NO_CACHE", False):
        return response
    
    if request.url.path.endswith((".css", ".js")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        if "ETag" in response.headers:
            del response.headers["ETag"]
            
    return response


# Mount the static folder for CSS and JS
app.mount("/static", StaticFiles(directory="static"), name="static")


async def stream_media_file(path: str, request: Request):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")

    file_size = os.stat(path).st_size
    mime_type, _ = mimetypes.guess_type(path)
    mime_type = mime_type or "application/octet-stream"
    
    range_header = request.headers.get("range")
    chunk_size = 1024 * 1024 

    start = 0
    end = file_size - 1
    status_code = 200

    if range_header:
        try:
            range_str = range_header.replace("bytes=", "")
            parts = range_str.split("-")
            start = int(parts[0])
            if parts[1]:
                end = int(parts[1])
            status_code = 206
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Range Header")

    end = min(end, file_size - 1)
    requested_len = (end - start) + 1

    async def generate_chunks():
        async with aiofiles.open(path, mode="rb") as f:
            await f.seek(start)
            remaining = requested_len
            while remaining > 0:
                to_read = min(chunk_size, remaining)
                chunk = await f.read(to_read)
                if not chunk:
                    break
                yield chunk
                remaining -= len(chunk)

    response_headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(requested_len),
    }
    
    if range_header:
        response_headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    return StreamingResponse(
        generate_chunks(),
        status_code=status_code,
        headers=response_headers,
        media_type=mime_type,
    )


@app.get("/background_video")
async def get_bg_video(path: str, request: Request):
    """Serves a background video by absolute path (supplied by /api/random_background)."""
    return await stream_media_file(path, request)

@app.get("/downloads/{file_name}")
async def get_download(file_name: str, request: Request):
    file_path = os.path.join(config.MEDIA_FOLDER, file_name)
    return await stream_media_file(file_path, request)


# Initialize Templates
templates = Jinja2Templates(directory="templates")

sio = AsyncServer(async_mode='asgi', cors_allowed_origins='*')
combined_asio_app = ASGIApp(sio, app)


async def broadcast_queue_update():
    await sio.emit('refresh_queue')
    showMessage("Queue Changed, Sending Sync Signal Out.")

async def broadcast_library_update():
    await sio.emit('refresh_library')
    showMessage("Media Library changed, Sending Sync Signal Out.")


def inject_translations(request: Request):
    lang = request.cookies.get("language", config.DEFAULT_LANG)
    translations = config.TRANSLATIONS.get(lang, config.TRANSLATIONS.get("en", {}))
    return {
        "t": translations,
        "current_lang": lang 
    }

templates.context_processors.append(inject_translations)

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("welcome.html", {"request": request})

@app.get("/search", response_class=HTMLResponse)
async def search_screen(request: Request):
    return templates.TemplateResponse("search.html", {"request": request})

@app.get("/library", response_class=HTMLResponse)
async def library_page(request: Request):
    return templates.TemplateResponse("library.html", {"request": request})

@app.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request):
    return templates.TemplateResponse("queue.html", {"request": request})

@app.get("/host", response_class=HTMLResponse)
async def host_screen(request: Request):
    return templates.TemplateResponse("host.html", {"request": request})


@app.post("/api/set_language")
async def set_language(data: dict, response: Response):
    lang = data.get("lang", "en")
    
    if lang not in config.TRANSLATIONS:
        return {"success": False, "message": "Language not supported"}
        
    response.set_cookie(key="language", value=lang, max_age=2592000, path="/")
    
    showMessage(f"Language Preference Updated To {lang}")
    return {"success": True, "lang": lang}

@app.get("/api/lyrics/auto")
async def auto_fetch_lyrics(title: str, artist: str):
    lyrics, status = await get_lyrics_auto(title.strip(), artist.strip())
    if lyrics:
        showMessage(f"Auto Lyrics ({len(lyrics)}): {status} Found For {title}")
        return {"success": True, "lyrics": lyrics, "status": status}
    showMessage("Finally Could Not Find Lyrics Online.")
    return {"success": False, "message": "Could Not Find Lyrics Online."}


@app.get("/api/system/info")
async def api_system_info():
    stats = await get_system_stats(".", config.BG_VIDEO_FOLDER, config.MEDIA_FOLDER)
    return stats


@app.get("/api/random_background")
async def get_random_background(request: Request, orientation: str = "landscape"):
    """
    Returns a URL for a random background video of the requested orientation.
    Orientation is auto-detected from video metadata (stored in videos.db).
    Falls back gracefully to opposite orientation if none found.
    """
    video_db: VideoDatabase = request.app.state.video_db
    file_path = await video_db.get_random(orientation)

    if not file_path:
        return {"url": None, "error": "No background videos found in library"}

    # Pass the path as a query param to the serving endpoint
    from urllib.parse import quote
    url = f"/background_video?path={quote(file_path)}"
    return {"url": url}


@app.post("/api/rescan_videos")
async def rescan_videos(request: Request):
    """Re-scans all bg_video_folder paths and updates videos.db."""
    video_db: VideoDatabase = request.app.state.video_db
    stats = await video_db.rescan()
    return {"success": True, **stats}


@app.get("/api/video_stats")
async def get_video_stats(request: Request):
    """Returns current video DB counts (no rescan)."""
    video_db: VideoDatabase = request.app.state.video_db
    return await video_db.get_stats()


# FIX #8: server_start_time explicitly initialised as None to clarify intent.
# It is only populated by handle_stage_update() when a song is actively loaded.
current_stage_info = {
    "status": "none",
    "title": None,
    "artist": None,
    "user_name": None,
    "file_url": None,
    "lrc": None,
    "media_type": None,
    "queue_id": None,
    "youtube_id": None,
    "volume": 80,
    "server_start_time": None  # FIX #8: Explicit None rather than absent key
}



@app.get("/api/host/current")
async def get_current_playing():
    global current_stage_info
    
    # If we already think it's empty, just return
    if not current_stage_info.get("queue_id"):
        return current_stage_info

    async with async_session() as db:
        # Check if this specific queue item still exists
        q_check = await db.execute(
            select(Queue).where(Queue.id == current_stage_info["queue_id"])
        )
        exists = q_check.scalar_one_or_none()

        # If it's gone from the queue, the song is finished/deleted
        if not exists:
            current_stage_info.update({
                "status": "none",
                "title": None, "artist": None, "user_name": None,
                "file_url": None, "lrc": None, "media_type": None,
                "queue_id": None, "youtube_id": None,
                "server_start_time": None
            })
            return current_stage_info

        # Optional: Sync title/artist if you allowed edits
        result = await db.execute(
            select(Song).where(Song.youtube_id == current_stage_info["youtube_id"])
        )
        song = result.scalar_one_or_none()
        if song:
            current_stage_info["title"] = song.title
            current_stage_info["artist"] = song.artist

    return current_stage_info


# Lock for /api/host/next — prevents two tabs from simultaneously fetching
# different songs. The second tab to arrive gets "already_handled" and stands down.
_next_lock = asyncio.Lock()
_last_served_queue_id = None


# --- CORE PLAYBACK & CONSOLIDATED LOGIC ---
@app.get("/api/host/next")
async def get_host_next():
    global _last_served_queue_id, current_stage_info

    async with _next_lock:
        async with async_session() as db:
            result = await db.execute(
                select(Queue, Song).join(Song).order_by(Queue.created_at.asc()).limit(1)
            )
            item = result.first()

            # IDLE CASE: Reset state inside the route
            if not item:
                # We reset the ID so that the next new song added will be seen as "new"
                _last_served_queue_id = None 
                
                current_stage_info.update({
                    "status": "none",
                    "title": None, "artist": None, "user_name": None,
                    "file_url": None, "lrc": None, "media_type": None,
                    "queue_id": None, "youtube_id": None,
                    "server_start_time": None
                })
                return {"status": "empty"}

            q, s = item
            
            # RE-SYNC CASE: If another client asks for 'next' while one is playing
            if q.id == _last_served_queue_id:
                return {**current_stage_info, "status": "already_handled"}

            # NEW SONG CASE: Set truth immediately
            _last_served_queue_id = q.id
            current_stage_info.update({
                "status": "success",
                "title": s.title,
                "artist": s.artist,
                "user_name": q.user_name or "Guest",
                "file_url": f'/downloads/{os.path.basename(s.file_path)}',
                "media_type": s.media_type,
                "lrc": s.lyrics,
                "queue_id": q.id,
                "youtube_id": s.youtube_id,
                "server_start_time": time.time() * 1000 
            })

            # Only broadcast the new song state to other clients when there IS a song
            # await sio.emit('force_load_new_song', current_stage_info)
            await broadcast_queue_update()
            return current_stage_info


@app.get("/qrcode")
async def get_qr():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except:
        ip = '127.0.0.1'
    finally:
        s.close()
    
    img = qrcode.make(f"http://{ip}:5555")
    buf = BytesIO()
    img.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


# --- API ENDPOINTS ---

@app.get("/api/search")
async def api_search(q: str, type: str):
    results = await search_media(q, type)
    return results

@app.post("/api/download")
async def api_download(request: Request):
    data = await request.json()
    requesting_user = data.get('user', 'Guest')
    
    youtube_id = data.get('id')
    media_type = data.get('type')
    suggested_title = data.get('title')
    suggested_artist = data.get('artist')

    async with async_session() as db:
        try:
            song, lyrics_status = await download_media(
                db, 
                youtube_id, 
                media_type, 
                config.MEDIA_FOLDER,
                suggested_title=suggested_title,
                suggested_artist=suggested_artist
            )
            if song is None:
                showMessage(f"Download Failed: {suggested_title} {suggested_artist} {lyrics_status}")
                return {
                    "success": False,
                    "message": f"{suggested_title} {suggested_artist} {lyrics_status}"
                }
                
            await add_to_queue(db, song.id, requesting_user)
            await db.commit()

            showMessage(f"Downloaded '{song.title}' - '{song.artist}' ({lyrics_status})")
            showMessage(f"Queued '{song.title}' - '{song.artist}' For {requesting_user}")

            await broadcast_library_update()
            await broadcast_queue_update()
            
            return {
                "success": True, 
                "title": song.title, 
                "artist": song.artist,
                "lyrics_status": lyrics_status
            }

        except Exception as e:
            await db.rollback()
            error_details = str(e)
            showMessage(f"Download ERROR: {error_details}")
            return {
                "success": False,
                "message": f"Failed to process request: {error_details}"
            }

@app.get("/api/library")
async def get_library(sort: str = "created_at"):
    async with async_session() as db:
        result = await db.execute(select(Song))
        songs = result.scalars().all()
        return [
            {
                "id": s.id,
                "title": s.title,
                "artist": s.artist,
                "lyrics": s.lyrics,
                "meta": s.meta,
                "rank": s.rank,
                "youtube_id": s.youtube_id,
                "type": s.media_type,
                "created_at": s.created_at.isoformat()
            } for s in songs
        ]

@app.put("/api/library/{song_id}")
async def update_song_metadata(song_id: int, data: dict):
    async with async_session() as db:
        raw_title = data.get('title', "").strip()
        raw_artist = data.get('artist', "").strip()
        new_lyrics = data.get('lyrics', "").strip()
        
        s_title, s_artist, meta_text = generate_meta_string(raw_title, raw_artist)

        await db.execute(
            update(Song)
            .where(Song.id == song_id)
            .values(
                title=s_title,      
                artist=s_artist,    
                lyrics=new_lyrics,
                meta=meta_text      
            )
        )
        await db.commit()

        showMessage(f"DB Record Updated For ID {song_id} ('{s_title} - {s_artist}')")
        
        await broadcast_library_update()
        await broadcast_queue_update()
        
        return {"success": True}

@app.delete("/api/library/{song_id}")
async def delete_song(song_id: int):
    async with async_session() as db:
        result = await db.execute(select(Song).where(Song.id == song_id))
        song = result.scalar_one_or_none()
        
        if song:
            full_name = f"{song.title} - {song.artist}"
            file_path = song.file_path
            
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError as e:
                    showMessage(f"File Deletion Failed:{full_name} {e}")
                    return {"success": False, "message": f"{full_name} {e}"}

            await db.execute(delete(Queue).where(Queue.song_id == song_id))
            await db.execute(delete(Song).where(Song.id == song_id))
            await db.commit()
            
            showMessage(f"Deleted '{full_name} {file_path}' From Library And Queue.")
            
            await broadcast_library_update()
            await broadcast_queue_update()
            
            return {"success": True}
            
        return {"success": False, "message": "Song Not Found In DB"}

@app.get("/api/queue")
async def get_queue_api():
    async with async_session() as db:
        result = await db.execute(
            select(Queue, Song)
            .join(Song)
            .order_by(Queue.created_at.asc())
        )
        queue_items = result.all()
        
        return [
            {
                "queue_id": q.id,
                "song_id": s.id,
                "title": s.title,
                "artist": s.artist,
                "youtube_id": s.youtube_id,
                "type": s.media_type,
                "user_name": q.user_name,
                "status": q.status
            } for q, s in queue_items
        ]

@app.delete("/api/queue/clear")
async def clear_queue_api():
    async with async_session() as db:
        # 1. Find the ID of the currently playing song (the oldest entry)
        first_item_query = await db.execute(
            select(Queue.id).order_by(Queue.created_at.asc()).limit(1)
        )
        first_id = first_item_query.scalar_one_or_none()

        if first_id is not None:
            # 2. Delete everything EXCEPT that first ID
            await db.execute(
                delete(Queue).where(Queue.id != first_id)
            )
            await db.commit()
            showMessage("Queue Cleared (Current Song Preserved).")
        else:
            # Queue was already empty
            showMessage("Queue Is Already Empty.")

        await broadcast_queue_update()
        return {"success": True}
    
@app.post("/api/queue/reorder")
async def reorder_queue(data: dict):
    new_ids = data.get("order", [])
    async with async_session() as db:
        start_time = datetime.now(timezone.utc) - timedelta(minutes=len(new_ids))
        
        for index, q_id in enumerate(new_ids):
            new_timestamp = start_time + timedelta(seconds=index)
            await db.execute(
                update(Queue)
                .where(Queue.id == q_id)
                .values(created_at=new_timestamp)
            )
        
        await db.commit()
        showMessage(f"Queue Reordered ({len(new_ids)} Items).")
        await broadcast_queue_update()
        return {"success": True}

@app.get("/api/queue/peek")
async def peek_queue():
    async with async_session() as db:
        result = await db.execute(
            select(Queue, Song)
            .join(Song)
            .order_by(Queue.created_at.asc())
            .limit(1)
            .offset(1)  # This skips the 'Current' song and grabs the 'Next' one
        )
        item = result.first()
        
        if not item:
            return {"status": "empty"}
            
        q, s = item
        return {
            "status": "success",
            "title": s.title,
            "artist": s.artist,
            "youtube_id": s.youtube_id,
            "user_name": q.user_name or "Guest"
        }

@app.post("/api/queue/finished/{queue_id}")
async def finish_song(queue_id: int):
    global _finished_ids

    async with _finishing_lock:
        if queue_id in _finished_ids:
            return {"status": "already_handled"}
        _finished_ids.add(queue_id)

    # We are the winner — do the actual delete outside the lock
    async with async_session() as db:
        result = await db.execute(select(Queue).where(Queue.id == queue_id))
        q = result.scalar_one_or_none()

        if not q:
            # Row already gone (e.g. cleared manually) — still our win, just log
            showMessage(f"Song {queue_id} Already Removed From DB.")
        else:
            await db.delete(q)
            await db.commit()
            showMessage(f"Song {queue_id} Finished And Removed.")

    await broadcast_queue_update()

    # Clean up the seen-set after 10 seconds
    async def _cleanup():
        await asyncio.sleep(10)
        _finished_ids.discard(queue_id)
    asyncio.create_task(_cleanup())

    return {"status": "success"}


@app.delete("/api/queue/{queue_id:int}")
async def remove_from_queue(queue_id: int):
    async with async_session() as db:
        await db.execute(delete(Queue).where(Queue.id == queue_id))
        await db.commit()
        showMessage(f"Removed Queue Item ID {queue_id}")
        await broadcast_queue_update()
        return {"success": True}
    

@app.post("/api/queue/random/{count}")
async def add_random_to_queue(count: int):
    async with async_session() as db:
        result = await db.execute(select(Song).order_by(func.random()).limit(count))
        random_songs = result.scalars().all()
        
        if not random_songs:
            return {"success": False, "message": "No songs found in library"}

        for song in random_songs:
            await add_to_queue(db, song.id, "RANDOM")
            
        await db.commit()
        await broadcast_queue_update()

        showMessage(f"Added and Committed {len(random_songs)} Random Songs.")
        return {"success": True, "added": len(random_songs)}


# --- SOCKET EVENTS ---

@sio.on('request_song')
async def handle_request(sid, data):
    song_db_id = data.get('id')
    requesting_user = data.get('user', 'Guest')
    
    async with async_session() as db:
        try:
            await add_to_queue(db, song_db_id, requesting_user)
            await db.commit()
            showMessage(f"Song ID {song_db_id} Added To Queue By {requesting_user}.")
            await broadcast_queue_update()
            
        except Exception as e:
            await db.rollback()
            showMessage(f"Could Not Add Song {song_db_id} To Queue: {e}")

@sio.on('media_control')
async def handle_media_control(sid, data):
    showMessage(f"Media Action Received: {data['action']}")
    await sio.emit('host_command', data)

@sio.on('volume_control')
async def handle_volume(sid, data):
    global current_stage_info
    current_stage_info["volume"] = data.get('level', 80)
    await sio.emit('host_volume', data)

@sio.on('volume_changed')
async def handle_volume_changed(sid, data):
    global current_stage_info
    current_stage_info["volume"] = data.get('level', 80)
    await sio.emit('volume_changed', data)


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


def wait_and_open_kiosk(host, port, section, appkiosk):
    url = f"http://{host}:{port}/{section}"
    
    for _ in range(30):
        try:
            if requests.get(url, timeout=1).status_code == 200:
                break
        except:
            pass
        time.sleep(0.5)

    if appkiosk == "kiosk":
        launch_args = ["--kiosk"]
    elif appkiosk == "app":
        launch_args = [f"--app={url}"]
    else:
        launch_args = ["--new-window"]

    if appkiosk != "app":
        launch_args.append(url)

    launch_args.append("--start-maximized")
    
    user_dir = os.path.join(os.environ['LOCALAPPDATA'], 'EdgeAppMode')
    launch_args.append(f"--user-data-dir={user_dir}")
    launch_args.append("--no-first-run")

    try:
        subprocess.Popen(["msedge"] + launch_args)
    except FileNotFoundError:
        cmd_str = f'start msedge ' + " ".join(launch_args)
        subprocess.Popen(cmd_str, shell=True)


if __name__ == "__main__":
    
    local_ip = get_local_ip()
    port = config.PORT
    section = "host"
    appkiosk = "regular"

    threading.Thread(target=wait_and_open_kiosk, args=(local_ip, port, section, appkiosk), daemon=True).start()
    
    uvicorn.run(
        "main:combined_asio_app", 
        host="0.0.0.0", 
        port=config.PORT, 
        reload=False,
        loop="auto",
        http="httptools"
    )