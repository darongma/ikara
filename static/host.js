const socket = io();

// --- State ---
let lyrics = [];
let oriLyric = "";
let currentQueueId = null;
let lastLoadedQueueId = null;
let isPlayerIdle = true;
let isCurrentlyLoading = false;

const player = document.getElementById('mainPlayer');
const bg = document.getElementById('bgVideo');


// --- Socket ---

socket.on('connect', () => console.log("Host connected:", socket.id));

// Another tab loaded a new song — sync to it
socket.on('force_load_new_song', (data) => setupPlayerWithData(data));

socket.on('refresh_queue', async () => {
    // 1. Always update the visual UI
    await updateNowPlaying();
    await fetchNextPreview();
    triggerManualSlide();

    // 2. Simple Auto-start logic
    // We only call loadNextSong if we are currently doing nothing.
    // The server-side lock will handle the rest.
    if (isPlayerIdle && !isCurrentlyLoading && currentQueueId === null) {
        console.log("Queue update detected. Attempting to start playback...");
        loadNextSong(); 
    }
});

// Remote control
socket.on('host_command', (data) => {
    if (data.action === 'toggle') {
        player.paused ? player.play() : player.pause();
        showNewStatus(t(player.paused ? 'status_pause' : 'status_resume'));
    } else if (data.action === 'restart') {
        player.currentTime = 0;
        player.play();
        showNewStatus(t('status_restart'));
    } else if (data.action === 'next') {
        showNewStatus(t('status_next'));
        // Trigger onended so the normal finished → loadNextSong flow runs
        player.dispatchEvent(new Event('ended'));
    }
});

socket.on('host_volume', (data) => {
    player.volume = data.level / 100;
    if (bg) { bg.muted = true; bg.volume = 0; }
});

socket.on('volume_changed', (data) => {
    showNewStatus(t('status_volume', { level: data.level }));
});


function toggleFullScreen() {
    const docElm = document.documentElement;
    
    // Check for standard or prefixed fullscreen methods
    const request = docElm.requestFullscreen || 
                    docElm.mozRequestFullScreen || 
                    docElm.webkitRequestFullScreen || 
                    docElm.msRequestFullscreen;
                    
    const exit = document.exitFullscreen || 
                 document.mozCancelFullScreen || 
                 document.webkitExitFullscreen || 
                 document.msExitFullscreen;

    if (!document.fullscreenElement && !document.webkitFullscreenElement) {
        request.call(docElm).catch(err => {
            console.log("Error: ", err.message);
        });
    } else {
        exit.call(document);
    }
}


// --- Core Logic ---
async function startHost() {
    const overlay = document.getElementById('startOverlay');
    if (overlay) overlay.style.display = 'none';

    try {
        const res = await fetch('/api/host/current');
        const data = await res.json();
        if (data && (data.file_url || data.youtube_id)) {
            setupPlayerWithData(data);
        } else {
            await loadNextSong();
        }
    } catch (e) {
        await loadNextSong();
    }
}

async function loadNextSong() {
    if (isCurrentlyLoading) return;
    isCurrentlyLoading = true;

    const stage = document.querySelector('.stage-wrapper');
    if (stage) stage.classList.add('transitioning');
    await new Promise(r => setTimeout(r, 800));

    try {
        const res = await fetch('/api/host/next');
        const data = await res.json();

        // Chained logic for all states
        if (data.status === 'success') {
            // ROLE: LEADER
            // We took the song from the queue. We must notify others.
            isPlayerIdle = false;            
            setupPlayerWithData(data);

        } else if (data.status === 'already_handled') {
            // ROLE: FOLLOWER / LATE-JOINER
            // The song is already "out" and the server has the start time.
            if (data.queue_id !== lastLoadedQueueId) {
                isPlayerIdle = false;
                setupPlayerWithData(data);
                console.log("Joined late, syncing to active song.");
            }
            if (stage) stage.classList.remove('transitioning');

        } else if (data.status === 'empty') {
            setIdleUI();
            isPlayerIdle = true;
            if (stage) stage.classList.remove('transitioning');
        }

        setTimeout(() => { isCurrentlyLoading = false; }, 500);
    } catch (e) {
        console.error("loadNextSong error:", e);
        isCurrentlyLoading = false;
        if (stage) stage.classList.remove('transitioning');
    }
}

function setupPlayerWithData(data) {
    if (!data || data.status === 'none') return;

    // Skip if this song is already loaded
    if (data.queue_id && data.queue_id === lastLoadedQueueId) {
        console.log("Already playing this song, skipping reload.");
        return;
    }

    lastLoadedQueueId = data.queue_id;
    currentQueueId = data.queue_id;
    isPlayerIdle=false;

    // UI
    document.querySelector('.bgblur').style.display = 'none';
    document.title = `${t('app_title')} - ${data.title} - ${data.artist} 🎤 ${data.user_name}`;
    document.getElementById('host-now-album-art').innerHTML =
        `<img class="thumb" src="https://img.youtube.com/vi/${data.youtube_id}/mqdefault.jpg"/>`;
    document.getElementById('displayTitle').innerText = `${data.title} - ${data.artist} 🎤`;
    document.getElementById('displayArtist').innerText = data.user_name;

    oriLyric = data.lrc;
    lyrics = parseLRC(data.lrc);
    fetchNextPreview();

    // Background video
    if (data.media_type === 'audio') {
        const orientation = window.innerWidth > window.innerHeight ? 'landscape' : 'portrait';
        fetch(`/api/random_background?orientation=${orientation}`)
            .then(r => r.json())
            .then(bgData => {
                if (!bgData.url) { stopBg(); return; }

                const newSrc = window.location.origin + bgData.url;
                if (bg.src !== newSrc) {
                    bg.pause();
                    bg.removeAttribute('src');
                    bg.load();
                    bg.src = bgData.url;
                }
                bg.style.display = 'block';
                bg.addEventListener('loadedmetadata', function () {
                    this.classList.remove('bg-portrait', 'bg-landscape');
                    document.querySelector('.bgblur').style.display = 'none';
                    const portrait = this.videoHeight > this.videoWidth;
                    this.classList.add(portrait ? 'bg-portrait' : 'bg-landscape');
                    if (portrait) document.querySelector('.bgblur').style.display = 'block';
                    this.play().catch(() => {});
                }, { once: true });
            });
    } else {
        stopBg();
    }

    // Audio player
    if (player._canplayHandler) {
        player.removeEventListener('canplay', player._canplayHandler);
        player._canplayHandler = null;
    }

    player.src = data.file_url;

    const canplayHandler = () => {
        player.removeEventListener('canplay', canplayHandler);
        player._canplayHandler = null;
        document.querySelector('.stage-wrapper')?.classList.remove('transitioning');

        // Simple sync
        if (data.server_start_time) {
            const offset = (Date.now() - data.server_start_time) / 1000;
            if (offset > 0.1 && offset < player.duration) {
                console.log(`Sync to ${offset.toFixed(1)}s`);
                player.currentTime = offset;
            }
        }

        player.play().catch(e => console.error("Play failed:", e));
    };
    player._canplayHandler = canplayHandler;
    player.addEventListener('canplay', canplayHandler);
    player.load();
}

// Every tab reports song end. Server's _finished_ids lock ensures
// only the first caller gets 'success' — the rest get 'already_handled'.
player.onended = async () => {
    if (!currentQueueId) return;

    isPlayerIdle = true;
    document.querySelector('.stage-wrapper')?.classList.add('transitioning');
    //clearLyricStage();

    // Small random spread
    await new Promise(r => setTimeout(r, Math.random() * 400));

    try {
        const res = await fetch(`/api/queue/finished/${currentQueueId}`, { method: 'POST' });
        const result = await res.json();
        loadNextSong();
    } catch (e) {
        console.error("onended error:", e);
    }
};


// --- UI Helpers ---

function stopBg() {
    bg.pause();
    bg.src = "";
    bg.removeAttribute('src');
    bg.load();
    bg.style.display = 'none';
}
function stopPlayer(){
    player.pause();
    player.src = "";
    player.removeAttribute('src');
    player.load();
}

function setIdleUI() {
    isPlayerIdle = true;
    currentQueueId = null; // Important: This flags that we are TRULY empty
    lastLoadedQueueId = null;
    const titleEl = document.getElementById('displayTitle');
    const artistEl = document.getElementById('displayArtist');
    if (titleEl) titleEl.innerText = t('status_ready');
    if (artistEl) artistEl.innerText = t('status_scan_qr');
    const albumArt=document.getElementById('host-now-album-art');
    if(albumArt)albumArt.innerHTML="";
    document.querySelector('.bgblur').style.display = 'none';
    stopBg();
    stopPlayer();
    setProgress(0, 0);
    clearLyricStage();
    console.log("Set Idle UI "+Date.now());
}

function clearLyricStage() {
    document.querySelectorAll(".lyric-row").forEach(el => el.innerHTML = "");
    console.log("Clear Lyric Stage "+Date.now());
}

async function updateNowPlaying() {
    try {
        const res = await fetch('/api/host/current');
        const data = await res.json();
        if (data.status === 'success') {
            document.title = `${t('app_title')} - ${data.title} - ${data.artist} 🎤 ${data.user_name}`;
            document.getElementById('displayTitle').innerText = `${data.title} - ${data.artist} 🎤`;
            document.getElementById('displayArtist').innerText = data.user_name;
            if (oriLyric && data.lrc && oriLyric !== data.lrc) lyrics = parseLRC(data.lrc);
        }
    } catch (e) { console.error("updateNowPlaying failed:", e); }
}

async function fetchNextPreview() {
    try {
        const res = await fetch('/api/queue/peek');
        const data = await res.json();
        const panel = document.getElementById('nextUpPanel');
        if (data && data.title) {
            panel.style.display = 'flex';
            document.getElementById('un-art').innerHTML =
                `<img class="thumb" src="https://img.youtube.com/vi/${data.youtube_id}/mqdefault.jpg"/>`;
            document.getElementById('nextSongInfo').innerHTML = `${data.title} - ${data.artist}`;
            document.getElementById('nextSinger').innerHTML = `🎤${data.user_name}`;
        } else {
            panel.style.display = 'none';
        }
    } catch (e) { console.log("fetchNextPreview failed:", e); }
}


// --- Progress bar & Lyrics (ontimeupdate) ---
function setProgress(cur, dur){
    if(dur==0) document.getElementById('progressFill').style.width = `0%`;
    else document.getElementById('progressFill').style.width = `${(cur / dur) * 100}%`;
    document.getElementById('currentTimeText').innerText = formatTime(cur);
    document.getElementById('durationText').innerText = formatTime(dur);
}

let lastLyricIdx = -2;
player.ontimeupdate = () => {
    if (isPlayerIdle) return;
    const cur = player.currentTime;
    const dur = player.duration;
    if (dur) {
        setProgress(cur, dur);
    }

    const idx = lyrics.findLastIndex(l => l.time <= cur);
    if (idx !== lastLyricIdx) {
        lastLyricIdx = idx;
        if (idx !== -1) {
            document.getElementById('currentLine').innerText = lyrics[idx].text;
            document.getElementById('prevLine').innerText = idx > 0 ? lyrics[idx - 1].text : '';
            document.getElementById('nextLine').innerText = idx < lyrics.length - 1 ? lyrics[idx + 1].text : '';
        } else {
            document.getElementById('prevLine').innerText = '';
            document.getElementById('currentLine').innerText = '';
            document.getElementById('nextLine').innerText = lyrics[0] ? lyrics[0].text : '';
        }
    }
};


// --- Utilities ---

function parseLRC(lrcText) {
    if (!lrcText) return [];
    const result = [];
    const reg = /\[(\d+):(\d+\.\d+)\]/g;
    lrcText.split('\n').forEach(line => {
        const matches = [...line.matchAll(reg)];
        if (matches.length) {
            const text = line.replace(reg, '').trim();
            matches.forEach(m => result.push({
                time: parseFloat(m[1]) * 60 + parseFloat(m[2]), text
            }));
        }
    });
    return result.sort((a, b) => a.time - b.time);
}

function formatTime(secs) {
    if (isNaN(secs)) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
}

function generateQRCode() {
    const el = document.getElementById('qrcode');
    if (el) { el.innerHTML = ''; new QRCode(el, { text: window.location.origin, width: 50, height: 50 }); }
}
document.addEventListener('DOMContentLoaded', generateQRCode);

function showNewStatus(msg) { showStatus(msg, '5px', '195px'); }


// --- Next Up Panel Animation ---

let stageTimers = [];

function runNextUpAnimation(dur) {
    const panel = document.getElementById('nextUpPanel');
    if (!panel) return;
    panel.classList.remove('active');
    stageTimers.forEach(clearTimeout);
    stageTimers = [];

    const slide = (delay, stay) => {
        const tIn = setTimeout(() => {
            if (panel.style.display !== 'none') {
                panel.classList.add('active');
                const tOut = setTimeout(() => panel.classList.remove('active'), stay);
                stageTimers.push(tOut);
            }
        }, delay);
        stageTimers.push(tIn);
    };

    slide(100, 7000);
    const mid = (dur * 1000) / 2;
    slide(mid, 5000);
    const end = (dur - 10) * 1000;
    if (end > mid + 8000) slide(end, 9000);
}

let isManualSliding = false;

function triggerManualSlide(stayFor = 5000) {
    const panel = document.getElementById('nextUpPanel');
    if (!panel || isManualSliding || panel.style.display === 'none') return;
    isManualSliding = true;
    panel.classList.remove('active');
    setTimeout(() => {
        panel.classList.add('active');
        setTimeout(() => {
            panel.classList.remove('active');
            setTimeout(() => { isManualSliding = false; }, 800);
        }, stayFor);
    }, 50);
}

player.onloadedmetadata = () => {
    if (player.duration > 0) runNextUpAnimation(player.duration);
};