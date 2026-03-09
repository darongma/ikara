document.addEventListener('DOMContentLoaded', () => {
    loadQueue();

// Initialize Drag & Drop
const el = document.getElementById('queueList');
if (el) {
    Sortable.create(el, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        handle: '.queue-card',
        
        // --- YOUR OPTIMIZATIONS ---
        forceFallback: false,
        fallbackTolerance: 15,
        delay: 70,
        delayOnTouchOnly: true,
        touchStartThreshold: 5,
        
        // --- PROTECTION LOGIC ---
        // Added '.locked' to your filter to disable dragging on item #1
        filter: '.actions, .locked', 
        preventOnFilter: false, 

        onMove: function (evt) {
            // This prevents dragging any item ABOVE the locked "Now Playing" item
            return !evt.related.classList.contains('locked');
        },

        onEnd: async function () {
            await saveNewOrder();
        },
    });
}

});

// 2. Self-aware Sync: Refresh when anyone else changes something
socket.on('refresh_queue', () => {
    console.log("Queue changed by another user. Syncing...");
    loadQueue(); 
});

async function loadQueue() {
    try {
        const res = await fetch('/api/queue');
        const songs = await res.json();
        renderQueue(songs);
    } catch (err) {
        console.error("Failed to load queue:", err);
    }
}

function renderQueue(songs) {
    const container = document.getElementById('queueList');
    if (!container) return;
    container.innerHTML = '';
    
    updateSongCount("songCountDisplay", songs.length, "🎧", "local_songs_found");
    
    if (songs.length === 0) {
        document.getElementById('clearq').style.display = "none";
        document.getElementById('empty-msg').style.display = "block";
        return;
    } else {
        document.getElementById('clearq').style.display = "block";
        document.getElementById('empty-msg').style.display = "none";
    }

    songs.forEach((item, index) => {
        const isFirst = index === 0;
        const card = document.createElement('div');
        
        // If it's the first song, add 'locked' class for Sortable and CSS
        card.className = `queue-card ${isFirst ? 'locked' : ''}`;
        card.setAttribute('data-id', item.queue_id);
        
        card.innerHTML = `
            <div class="queue-index">
                ${isFirst ? '▶️' : index + 1}
            </div>
            <img class="thumbq" src="https://img.youtube.com/vi/${item.youtube_id}/mqdefault.jpg">
            <div class="info">
                <strong>${item.title} ${isFirst ? '' : ''}</strong>
                <small>${item.artist} - ${item.user_name || 'Anonymous'}</small>
            </div>
            <div class="actions">
                ${!isFirst ? `
                    <button type="button" class="btn btn-del" data-id="${item.queue_id}">
                        ✖️
                    </button>
                ` : ''}
            </div>
        `;

        // Only attach delete listener if the button exists (not for index 0)
        const delBtn = card.querySelector('.btn-del');
        if (delBtn) {
            delBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                removeFromQueue(item.queue_id, item.title);
            });
        }

        container.appendChild(card);
    });
}

async function saveNewOrder() {
    const container = document.getElementById('queueList');
    const newOrder = Array.from(container.children).map(child => 
        parseInt(child.getAttribute('data-id'))
    );

    const res = await fetch('/api/queue/reorder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order: newOrder })
    });

    if (res.ok) {
        // showStatus(t('queue_order_updated'));
        // reload handled by the broadcast usually, but we call it here for immediate index update
        loadQueue();
    }
}

async function removeFromQueue(queueId, title) {
    try {
        const res = await fetch(`/api/queue/${queueId}`, { method: 'DELETE' });
        if (res.ok) {
            loadQueue();
            showStatus(`${title} ${t('queue_removed')}`);
        }
    } catch (err) {
        console.error("Delete error:", err);
    }
}

async function clearQueue() {
    if (!confirm(t('queue_confirm_clear'))) return;
    
    try {
        const res = await fetch('/api/queue/clear', { 
            method: 'DELETE',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            }
        });
        
        if (res.ok) {
            
            showStatus(t('queue_cleared'));
            loadQueue(); 
        }
    } catch (err) {
        console.error("Network error:", err);
        showStatus(t('queue_clear_error'));
    }
}

async function randomQueue(count) {
    const btn = document.getElementById('randomq');
    
    
    try {
        btn.disabled = true;

        const res = await fetch(`/api/queue/random/${count}`, { method: 'POST' });
        const data = await res.json();

        if (data.success) {
            //showStatus(t('queue_added_random', { count: data.added }));
        }
    } catch (err) {
        showStatus(`${t('queue_random_error')} ${err}`);
    } finally {
        btn.disabled = false;
    }
}

