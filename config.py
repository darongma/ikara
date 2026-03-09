import os
import json
import subprocess
import sys
from downloader import showMessage

CONFIG_FILE = "config.json"


DEFAULTS = {
    "db_folder": r"C:\KALAOK",
    "media_folder": r"C:\KALAOK\DOWNLOAD",
    "bg_video_folder": [r"C:\KALAOK\LOCAL-VIDEO"], # Default is now a list
    "default_volume": 80,
    "port":5555
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULTS, f, indent=4)
        return DEFAULTS
    
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, IOError):
        return DEFAULTS

    for key, default_val in DEFAULTS.items():
        current_val = config.get(key)

        # --- SPECIAL CASE: Multiple Background Video Folders ---
        if key == "bg_video_folder":
            # 1. Normalize to list
            if isinstance(current_val, str):
                current_val = [current_val]
            
            if not isinstance(current_val, list):
                current_val = default_val if isinstance(default_val, list) else [default_val]

            # 2. Validate paths
            valid_paths = [p for p in current_val if os.path.exists(p)]

            if not valid_paths:
                showMessage(f"Warning: All paths for {key} invalid. Using default.")
                config[key] = default_val if isinstance(default_val, list) else [default_val]
            else:
                config[key] = valid_paths

        # --- STANDARD CASE: All other folders (Single Strings) ---
        elif key.endswith("_folder"):
            if not current_val or not os.path.exists(str(current_val)):
                showMessage(f"Path For {key} Invalid. Reverting To Default: {default_val}")
                config[key] = default_val
            else:
                config[key] = current_val

    return config



def save_config(updates: dict):
    try:
        full_config = load_config()
        
        # 1. Normalize bg_video_folder specifically
        if "bg_video_folder" in updates:
            val = updates["bg_video_folder"]
            # If it's a string, make it a list for consistency
            if isinstance(val, str):
                updates["bg_video_folder"] = [val]
        
        # 2. Update the full config dictionary
        full_config.update(updates)
        
        # 3. Write to JSON
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(full_config, f, indent=4)
        
        # 4. Correcting global assignments
        global NO_CACHE, DB_FOLDER, MEDIA_FOLDER, BG_VIDEO_FOLDER, DEFAULT_VOLUME, DB_PATH, DATABASE_URL
        
        # db_folder remains a single string
        if "db_folder" in updates: 
            DB_FOLDER = updates["db_folder"]
            DB_PATH = os.path.join(DB_FOLDER, "karaoke.db")
            DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"
            
        # media_folder remains a single string
        if "media_folder" in updates: 
            MEDIA_FOLDER = updates["media_folder"]
            
        # bg_video_folder is now ALWAYS a list
        if "bg_video_folder" in updates: 
            BG_VIDEO_FOLDER = updates["bg_video_folder"]
            
        if "default_volume" in updates: 
            DEFAULT_VOLUME = updates["default_volume"]
            
        showMessage(f"Config Updated. Keys: {list(updates.keys())}")
        return True

    except Exception as e:
        showMessage(f"Error Saving Config: {e}")
        return False


def load_translations():
    path = "translations.json"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            showMessage(f"Loaded Languages: {list(data.keys())}")
            return data
    return {}


def reload_settings():
    global SYS_SETTINGS, NO_CACHE, DB_FOLDER, MEDIA_FOLDER, BG_VIDEO_FOLDER, DEFAULT_VOLUME, DB_PATH, DATABASE_URL, PORT
    SYS_SETTINGS = load_config()
    DB_FOLDER = SYS_SETTINGS.get("db_folder")
    MEDIA_FOLDER = SYS_SETTINGS.get("media_folder")
    BG_VIDEO_FOLDER = SYS_SETTINGS.get("bg_video_folder")
    DEFAULT_VOLUME = SYS_SETTINGS.get("default_volume")
    NO_CACHE = SYS_SETTINGS.get("no_cache")
    DB_PATH = os.path.join(DB_FOLDER, "karaoke.db")
    DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"
    PORT=SYS_SETTINGS.get("port")

def update_ytdlp():
    showMessage("Checking For yt-dlp Updates...")
    try:
        # This calls: pip install -U yt-dlp[default]
        # [default] ensures you get the recommended dependencies too
        # subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"])
        showMessage("yt-dlp Is Up To Date!")
    except Exception as e:
        showMessage(f"yt-dlp Update Failed: {e}")
    return "YEAH"


def print_splash_screen():
    # New ASCII Art for "i kara u ok"
    art = r"""
      _  _  _   __    ____    __   
     (_)| |/ / /  \  |  _ \  /  \  
      _ |   < / /\ \ | |_) )/ /\ \ 
     | || |\ \  __  ||  _  /  __  |
     |_||_| \_\/  \_\|_| \_\/    \_|

           --- iKARA uOK ---
    """
    
    width = 70
    print(art)
    print("=" * width)
    print(f"{'iKARA uOK - SERVER CONFIGURATION':^{width}}")
    print("=" * width)
    
    # 1. Main Folders
    print(f"[*] DB Folder:      {DB_FOLDER}")
    print(f"[*] Media Folder:   {MEDIA_FOLDER}")
    
    # 2. Multiple Background Folders (orientation auto-detected via ffprobe)
    print("[*] BG Video Folders:")
    if isinstance(BG_VIDEO_FOLDER, list):
        for i, path in enumerate(BG_VIDEO_FOLDER, 1):
            print(f"    {i}. {path}")
    else:
        print(f"    1. {BG_VIDEO_FOLDER}")
    print("[*] Orientation: Auto-detected via ffprobe (stored in videos.db)")

    # 3. Server & App Settings
    print("-" * width)
    print(f"[*] Default Volume: {DEFAULT_VOLUME}%")
    print(f"[*] No Cache Mode:  {NO_CACHE}")
    print(f"[*] Database Path:  {DB_PATH}")
    
    # 4. Credits
    print("-" * width)
    print(f"Developer: Darong Ma 馬達榮 | Email: darongma@yahoo.com")
    print("=" * width)
    print("\n")



reload_settings()
print_splash_screen()
newytdlp=update_ytdlp()
TRANSLATIONS = load_translations()
DEFAULT_LANG = "en"  # Hardcode to "zh" for now to force the test



