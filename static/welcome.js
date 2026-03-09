/**
 * welcome.js
 * Remote control logic for the Welcome Page
 */

document.addEventListener('DOMContentLoaded', () => {
    updateNowPlaying();
    fetchNextPreview();
    if (typeof socket !== 'undefined') {
        attachSocketListeners();
    } else {
        console.error("Socket not found. Retrying in 500ms...");
        setTimeout(() => {
            if (typeof socket !== 'undefined') attachSocketListeners();
        }, 500);
    }
});

function attachSocketListeners() {
    socket.on('refresh_queue', () => {
        console.log("Media Library refresh received, updating Now Playing...");
        setTimeout(updateNowPlaying, 300);
        setTimeout(fetchNextPreview, 300);
    });
    

    // SYNC VOLUME FROM OTHER CLIENTS
    socket.on('host_volume', (data) => {
        // Only update if the user isn't currently touching the slider
        // This prevents the slider from "jumping" while you are sliding it
        const volSlider = document.getElementById('volumeSlider');
        if (volSlider && document.activeElement !== volSlider) {
            console.log("Syncing volume from server:", data.level);
            syncVolumeUI(data.level);
        }
    });

    socket.on('connect', () => {
        console.log("Remote Control: Socket Connected");
    });
}

/**
 * Updates the UI elements without emitting a socket event
 */
function syncVolumeUI(level) {
    const volSlider = document.getElementById('volumeSlider');
    const volLabel = document.getElementById('volLabel');
    
    if (volSlider) volSlider.value = level;
    if (volLabel) volLabel.innerText = level + "%";
}

async function updateNowPlaying() {
    try {
        const res = await fetch('/api/host/current');
        const data = await res.json();
        
        const titleEl = document.getElementById('ctrlTitle');
        
        if (data.status === "success") {
            document.getElementById('now-album-art').innerHTML =`<img class="thumb" src="https://img.youtube.com/vi/${data.youtube_id}/mqdefault.jpg"/>`
            titleEl.innerHTML = `${data.title}<br><small>${data.artist}</small><p id="ctrlInfo"><b style="font-size:20px;">🎤</b>${data.user_name}</p>`;
            console.log(`NOW PLAYING: ${data.title} - ${data.artist} covered by ${data.user_name}`);
            if (data.volume !== undefined) {
                syncVolumeUI(data.volume);
            }
        } else {
            // FIXED: Use the translated text from the HTML attribute instead of hardcoded English
            titleEl.innerText = titleEl.dataset.idle || "Stage is Idle";
        }
    } catch (err) {
        console.error("Failed to fetch current song:", err);
    }
}

function sendMediaControl(action) {
    if (typeof socket === 'undefined') return;
    
    socket.emit('media_control', { action: action });
    
    if (action === 'next') {
        setTimeout(updateNowPlaying, 600);
        setTimeout(fetchNextPreview, 600);
    }
    
    
}

/**
 * Consolidated Volume Handler
 */
function handleVolumeChange(val) {
    const volumeLevel = parseInt(val);
    
    // 1. Update UI Label locally
    const volLabel = document.getElementById('volLabel');
    if (volLabel) volLabel.innerText = volumeLevel + "%";
    
    // 2. Send to Socket
    if (typeof socket !== 'undefined') {
        socket.emit('volume_control', { level: volumeLevel });
    }
}
function volumeChanged(val){
    const volumeLevel = parseInt(val);
    socket.emit('volume_changed', { level: volumeLevel });
    console.log("Remote Page Set Volume " + volumeLevel);
}
// Compatibility wrappers
function updateVolUI(val) { handleVolumeChange(val); }
function sendVolume(val) { handleVolumeChange(val); }

async function fetchNextPreview() {
    try {
        const res = await fetch('/api/queue/peek');
        const data = await res.json();
        const panel = document.getElementById('nextUpPanel');
        
        if (data && data.title) {
            panel.style.display = 'block';
            document.getElementById('album-art').innerHTML =`<img class="thumb" src="https://img.youtube.com/vi/${data.youtube_id}/mqdefault.jpg"/>`
            document.getElementById('nextSongInfo').innerHTML = `${data.title}<br><small>${data.artist}</small><p id="nextSinger">🎤${data.user_name}</p>`;
        } else {
            panel.style.display = 'none';
        }
    } catch (e) {
        console.log("Peek failed", e);
    }
}