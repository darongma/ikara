import psutil
import os
import platform
import asyncio
from downloader import showMessage

def get_folder_info(path):
    """Calculates total size in bytes and counts the number of files."""
    total_size = 0
    file_count = 0
    
    try:
        if not os.path.exists(path):
            return 0, 0
            
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                # Skip symbolic links to avoid double-counting or infinite loops
                if not os.path.islink(fp):
                    try:
                        total_size += os.path.getsize(fp)
                        file_count += 1
                    except OSError:
                        # Handles files that might disappear or be locked
                        continue
                        
    except Exception as e:
        showMessage(f"Error calculating folder info: {e}")
        return 0, 0
        
    return total_size, file_count

def format_size(bytes_val):
    """Formats bytes to MB or GB for readability."""
    if bytes_val < 1024**3:
        return f"{bytes_val / (1024**2):.2f}MB"
    else:
        return f"{bytes_val / (1024**3):.2f}GB"

def get_system_stats_sync(app_path, bg_path_list, media_path):
    """Performs system checks, now aggregating multiple bg folders."""
    # 1. Standard System Metrics
    cpu_usage = psutil.cpu_percent(interval=0.1) 
    usage = psutil.disk_usage(os.path.abspath(os.sep))
    mem = psutil.virtual_memory()
    
    # 2. Folder Info: Background Videos (Aggregated)
    total_bg_size = 0
    total_bg_count = 0
    
    # Ensure bg_path_list is a list (even if a single string is passed)
    folders_to_scan = bg_path_list if isinstance(bg_path_list, list) else [bg_path_list]
    folders_has_file=[]
    for folder in folders_to_scan:
        if os.path.exists(folder):
            size_raw, file_count = get_folder_info(folder)
            total_bg_size += size_raw
            total_bg_count += file_count
            if file_count>0:
                folders_has_file.append(folder)

    # 3. Folder Info: Media
    media_size_raw, media_file_count = get_folder_info(media_path)
    
    return {
        "cpu_load": f"{cpu_usage}%",
        "disk_free": f"{usage.free // (2**30)}GB",
        "disk_total": f"{usage.total // (2**30)}GB",
        "memory_free": f"{mem.available // (2**30)}GB", 
        "memory_total": f"{round(mem.total / (2**30), 1)}GB",
        "os_name": platform.system(),
        "app_folder": os.path.abspath(app_path),
        # Join the list into a readable string for the UI
        "bg_folder": ", ".join([os.path.abspath(p) for p in folders_has_file]),
        "bg_folder_size": format_size(total_bg_size),
        "bg_file_count": total_bg_count,
        "media_folder": os.path.abspath(media_path),
        "media_folder_size": format_size(media_size_raw),
        "media_file_count": media_file_count,
        "developer": "Darong Ma 馬達榮",
        "email": "darongma@yahoo.com",
        "website":"https://www.darongma.com",
        "paypal":"https://paypal.me/darongma"
    }

async def get_system_stats(app_path, bg_path, media_path):
    """The async wrapper to prevent UI stutter."""
    return await asyncio.to_thread(get_system_stats_sync, app_path, bg_path, media_path)