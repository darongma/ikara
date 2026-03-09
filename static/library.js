let cachedSongs = [];

document.addEventListener('DOMContentLoaded', () => {

    loadLibrary();

    document.getElementById('libSearch').addEventListener('input', filterLibrary);
    try{
        document.getElementById('cancelEditBtn').addEventListener('click', closeModal);
        document.getElementById('saveEditBtn').addEventListener('click', saveEdit);
    }
    catch(e){

    }

});



const artistIndex = document.getElementById('artistIndex');
let scrollTimeout;

window.addEventListener('scroll', () => {
    if (!artistIndex) return;

    // 1. Show the index if scrolled down
    if (window.scrollY > 200) {
        artistIndex.classList.add('visible');
    } else {
        artistIndex.classList.remove('visible');
    }

    // 2. Clear the timeout every time the user is moving
    // This works on iOS even during momentum/rubber-banding
    clearTimeout(scrollTimeout);

    // 3. Set a timer to hide it 3 seconds after the LAST scroll event
    scrollTimeout = setTimeout(() => {
        // Only hide if we aren't near the top
        if (window.scrollY > 200) {
            artistIndex.classList.remove('visible');
        }
    }, 3000);
});






async function autoUpdateLyrics(btn) {
    const title = document.getElementById('editTitle').value;
    const artist = document.getElementById('editArtist').value;
    const lyricsArea = document.getElementById('editLyrics');

    if (!title) {
        showStatus(t('status_enter_title'));
        return;
    }

    // 1. Check for existing content and confirm
    if (lyricsArea.value.trim() !== "") {
        if (!confirm(t('confirm_overwrite_lyrics'))) return;
    }

    // 2. Prepare UI: Store current lyrics, clear field, and disable button
    const originalBtnText = btn.innerHTML;
    const originalLyrics = lyricsArea.value;

    lyricsArea.value = ""; 
    lyricsArea.placeholder = t('placeholder_searching_lyrics');
    btn.disabled = true;
    btn.innerHTML = "⌛";

    try {
        const resp = await fetch(`/api/lyrics/auto?title=${encodeURIComponent(title)}&artist=${encodeURIComponent(artist)}`);
        const data = await resp.json();

        if (data.success) {
            lyricsArea.value = data.lyrics;
            showStatus(`${t('status_lyrics_success')}: ${data.status}`);
        } else {
            showStatus(t('status_no_lyrics') || data.message);
            // Restore original content since search failed
            lyricsArea.value = originalLyrics;
        }
    } catch (err) {
        console.error("Auto Lyrics Fetch Error:", err);
        showStatus(t('status_lyrics_error'));
        // Restore original content since fetch failed
        lyricsArea.value = originalLyrics;
    } finally {
        // 3. Restore Button UI state
        btn.disabled = false;
        btn.innerHTML = originalBtnText;
        lyricsArea.placeholder ="";
        // The placeholder will naturally be hidden if lyrics were restored or found
    }
}

function generateArtistIndex(songs, min) {
    const container = document.getElementById('artistIndex');
    if (!container) return;
    container.innerHTML = '';

    // 1. Count occurrences of each first character
    const charCounts = songs.reduce((acc, s) => {
        const char = s.artist.trim().charAt(0);
        if (char && char.match(/[\u4e00-\u9fa5]/)) {
            acc[char] = (acc[char] || 0) + 1;
        }
        return acc;
    }, {});

    // 2. Filter by the min parameter and Sort
    const sortedChars = Object.keys(charCounts)
        .filter(char => charCounts[char] >= min) // Only include if count >= min
        .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));

    // 3. Render the sorted list
    sortedChars.forEach(char => {
        const span = document.createElement('span');
        span.className = 'index-char';
        span.innerText = char;
        span.onclick = () => {
            const searchInput = document.getElementById('libSearch');
            searchInput.value = char;
            if (typeof filterLibrary === 'function') filterLibrary();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        };
        container.appendChild(span);
    });
}

async function loadLibrary() {
    // Get sort value from the currently active anchor link
    const activeSort = document.querySelector('.sort-link.active')?.dataset?.sort || "created_at";
    const res = await fetch(`/api/library?sort=${activeSort}`);
    cachedSongs = await res.json();
    applySortAndRender();
}


// 2. The Sorting Function (Purely Client-Side)
function applySortAndRender() {
    const activeSort = document.querySelector('.sort-link.active')?.dataset?.sort || "created_at";

    cachedSongs.sort((a, b) => {
        if (activeSort === 'title' || activeSort === 'artist') {
            // Pinyin-aware sorting for Chinese/English strings
            // return a[activeSort].localeCompare(b[activeSort], 'zh-Hans-CN');
            return a[activeSort].localeCompare(b[activeSort], 'zh-Hans-CN', {
  sensitivity: 'accent',
  numeric: true
});
        } else if (activeSort === 'rank') {
            // Numbers: Highest rank first
            return (b.rank || 0) - (a.rank || 0);
        } else if (activeSort === 'created_at') {
            // Dates: Newest first
            return new Date(b.created_at) - new Date(a.created_at);
        }
        return 0;
    });

    //renderLibrary(cachedSongs);
    filterLibrary();
    generateArtistIndex(cachedSongs, 5);
}

// 3. Update Event Listeners
document.querySelectorAll('.sort-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        document.querySelectorAll('.sort-link').forEach(l => l.classList.remove('active'));
        link.classList.add('active');
        
        // No fetch needed! Just re-sort the cached data.
        applySortAndRender(); 
    });
});


function renderLibrary(songs) {
    const container = document.getElementById('libraryList');
    container.innerHTML = '';

    songs.forEach(song => {
    const card = document.createElement('div');
    card.className = 'song-card';

    card.innerHTML =`
        <img class="thumb" src="https://img.youtube.com/vi/${song.youtube_id}/mqdefault.jpg">
        <div class="info">
            <strong>${song.title}</strong>
            <small>${song.artist}</small>
        </div>
        <div class="actions">
            <button class="btn btn-edit">📝</button>
        </div>
    `;


    const editBtn = card.querySelector('.btn-edit');

     card.onclick = (e) => {
        e.stopPropagation();
        addToQueue(song); // This works perfectly!
    };
    

    editBtn.onclick = (e) => {
        e.stopPropagation();
        openEdit(song.id);
    };

    container.appendChild(card);
    });

    updateSongCount("libsongCountDisplay",songs.length, "🎧", "local_songs_found");
}
async function addToQueue(song) {
    const userName = localStorage.getItem('karaoke_name') || 'Guest';
    
    if (typeof socket !== 'undefined' && socket.connected) {
        // CHANGED: Use song.id (the database integer) 
        // to match the backend add_to_queue(db, song_id, user)
        socket.emit('request_song', {
            id: song.id, 
            user: userName
        });
        message = `${song.title} - ${song.artist} ${t('status_added_queue')}`;
        showStatus(message);
        
        // Front-end Server Side: Confirmation
        // The message will fade in for 3-5s and then fade out as per your preferences.
    } else {
        showStatus(t('status_queue_error'));
    }
}

function filterLibrary() {
    const query = document.getElementById('libSearch').value.toLowerCase();
    
    const filtered = cachedSongs.filter(s => 
        s.meta && s.meta.toLowerCase().includes(query)
    );
    
    renderLibrary(filtered);
}

// Updated openEdit to pull from cachedSongs and include lyrics
function openEdit(id) {
    const song = cachedSongs.find(s => s.id === id);
    if (!song) return;

    document.getElementById('editId').value = song.id;
    document.getElementById('editTitle').value = song.title;
    document.getElementById('editArtist').value = song.artist;
    
    const lyricsArea = document.getElementById('editLyrics');
    if (lyricsArea) {
        lyricsArea.value = song.lyrics || "";
    }
    
    const thumbImg = document.getElementById('editThumb');
    thumbImg.src = `https://img.youtube.com/vi/${song.youtube_id}/mqdefault.jpg`;


    // Hook up the DELETE button in the modal footer to use your version
    const delBtn = document.getElementById('deleteEditBtn');
    delBtn.onclick = () => {
        deleteSong(song.id, song.title);
    };
    
    document.getElementById('editModal').style.display = 'flex';
}

function closeModal() {
    document.getElementById('editModal').style.display = 'none';
}

async function saveEdit() {
    const id = document.getElementById('editId').value;
    const title = document.getElementById('editTitle').value;
    const artist = document.getElementById('editArtist').value;
    
    const lyricsArea = document.getElementById('editLyrics');
    const lyrics = lyricsArea ? lyricsArea.value : "";

    const res = await fetch(`/api/library/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, artist, lyrics })
    });

    if (res.ok) {
        closeModal();
        loadLibrary();
        message = `${title} - ${artist} ${t('status_updated')}`;
        showStatus(message);
    }
}

async function deleteSong(id, title) {
    if (!confirm(`${t('confirm_delete_song')} "${title}"?`)) return;

    const res = await fetch(`/api/library/${id}`, { method: 'DELETE' });
    const data = await res.json(); // Parse the JSON response

    if (res.ok && data.success) {
        closeModal(); 
        loadLibrary();
        message = `${title} ${t('status_deleted')}`;
        showStatus(message);
    } else {
        // Handle the failure case
        showStatus(`${t('status_deletion_failed')} ${data.message}`);
    }
}

// Socket listener
if (typeof socket !== 'undefined') {
    socket.on('refresh_library', () => {
        console.log("Library update received from server. Refreshing list...");
        loadLibrary();
    });
}