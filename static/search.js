document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('searchVideoBtn').addEventListener('click', () => handleSearchOrDirectLink('video'));
    document.getElementById('searchAudioBtn').addEventListener('click', () => handleSearchOrDirectLink('audio'));
    
    document.getElementById("libSearch").addEventListener('input', (e) => {
        const searchInput = document.getElementById("libSearch");
        const input = searchInput.value.trim();
        const library = document.getElementById("localLibrary");
        const libCount=document.getElementById("libsongCountDisplay");
        if (input=="") {
            if (library) {
            library.style.display = "none";}
            return;
        }
        if (e.key === 'Enter') handleSearchOrDirectLink('video');
        else{
            
            if (library) {
                library.style.display = "block";
            }
        }
    });
});



async function handleSearchOrDirectLink(type) {
    const searchInput = document.getElementById("libSearch");
    const input = searchInput.value.trim();
    if (!input) return;

    const ytRegex = /(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^"&?\/\s]{11})/;
    const match = input.match(ytRegex);

    if (match && match[1]) {
        const videoId = match[1];
        
        try {
            await download(videoId, type, "YouTube Link", "Unknown Artist");
            searchInput.value = ""; 
            console.log("[SERVER]: Input cleared after direct link success.");
        } catch (err) {
            console.error("Input preserved due to download failure.");
        }
    } else {
        search(type, input);
    }
}

async function search(type, query) {
    const list = document.getElementById("resultsList");
    
    icontype="🎬";
    if(type=="audio") icontype="🎧";
    
    list.innerHTML = `<p style='text-align:center;'>${t("search_loading")}</p>`;

    try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}&type=${type}`);
        const data = await response.json();

        list.innerHTML = "";
        
        if (data.length === 0) {
            list.innerHTML = `<p style='text-align:center;'>${t("no_results")}</p>`;
            updateSongCount("songCountDisplay",0, icontype, "songs_found");
            return;
        }

        data.forEach((item) => {
            const card = document.createElement("div");
            card.className = "result-card";

            const escapedTitle = item.title.replace(/'/g, "\\'").replace(/"/g, "&quot;");
            const escapedArtist = item.artist.replace(/'/g, "\\'").replace(/"/g, "&quot;");

            card.innerHTML = `
                <img src="${item.thumbnail}" class="thumb">
                <div class="info">
                    <strong>${item.title}</strong>
                    <small>${item.artist}</small>
                </div>
                <button class="dl-btn" 
                    data-id="${item.id}" 
                    data-type="${type}" 
                    data-title="${escapedTitle}" 
                    data-artist="${escapedArtist}">
                    <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAACXBIWXMAAAsTAAALEwEAmpwYAAAEDElEQVR4nO2Y2W4iRxSG60V8nTdJLqJEkZLczE0mUjRRNHFmYpJpbLABu7GNscFgaLamaTY3SzfNTrPa80ATKX6BP2LzmJGpxsSKS5E/6b+rI9WnPlV1gJBnnmEPxTA2it2mWui2bordFu6GsI5i6BvZZu1DrlXHfSGsI9UqaqquY1kI68Q09SZe0bAshHXC5RJoIaxzrhRAC2Edby4PWgjrHMpZ0EJYx5WUQQthHXssCVoI63BCArQQ1tkKRkELYZ1NvwBaCOv84r0ALYR1fjoOgBbCOj/wPtBCWOeF6xS0ENb5ftcDWgjrfLNzCFoI63z5jgcthHU+t7hAC2EBXs5wbjmDxwwvZxyPsrlgrIhARLk5jyi6Xyh9tmzdXlziHIkUHiN7cWnp5rds4Y3N7bD62hq6ec2FzL9gKFHCRbyEsch5rPjXaVjZWLbWKojcdkTEv4lVEKmbf2MTPry1RfDGJuC3nRVGkYikQkiWERZLmMoUS7T1losoZ7mIYZ1sBaPUtrE4oqrFEcPWXhS/70bx1h4xF4jLGmIpFVFJRSRZhpAo/21Ws3kmcJu+MB6SX30h057nXPGbd644/nTG8YcjBstezFwgmalATFeQSGuYy5gWEUJeeQLczydBrJJXJ8GVDuwOL2L7QIR1PwFuP4GxjGlRKl+FlNORzOoQM2ORyspX30vez/3o9oOWl7xv5dvGfiTBdpjEjjuJbV6E9UA030tGqSF9WYOcryKVm8qQB/DC6eWWzkLO0wddlQ5PCnvHKeweSbAfSrC5V/hJmi82kCvUkS3UMZchD+Rbu4f7bteDhdiPH3zP73vTcJ3IcJ6kMJWRzPeiqE1clpvIlxrIFRsTEbIGX1l57murG9Pwaz1Sbl8G/FkaB6dp7HvliYxpUanSQlFroaA2oZTHMo21n/8vLC7nOOvWH51ncejPYiqSwcFZ2nwvWrUDtdpGWW9jLkOeiJNgHp5ADseBHOYypkXVhgG9bqBS62Aio7efTOAsfInT0CW8F3nMZUyL6q0eas0uqo0u9IaBSt14MoHzSAF+QYEvrOAsNJUxLWoZfTQ7fTTaPSzITL6KAa02brHOQovdPS/Tw794i02u5Hvel/jkodQQTan4OMKUcXceC4xnsmgB/ogCn6CYCxi9ITrdAdrGAK1OH832XKY7k/mkxT45L7cyJYpMjiIj3ZW5ncemMtEV/p7vD0bo9Yfo9ocweoOZTH8m00Oj1UO9uURGb6NcWSJzz/siz2WyOiYjTGZxhLmdx8SPMqYCw6srDEZX6A9H6A1GM5HZV+kOsLTFZudlscXaUxGthcX35Y6IUoN8uaTF0hpi8rTF5jKmAtfv3+Pq+hqjq2sMRxSZeYv9x+eFPPPMM/8v/gGPd8BLylsUCgAAAABJRU5ErkJggg==" alt="download">
                </button>
            `;
            
            const dlBtn = card.querySelector('.dl-btn');
            dlBtn.addEventListener('click', async function() {
                this.disabled = true;
                this.classList.add('loading');
                const originalContent = this.innerHTML;
                this.innerHTML = "⌛"; 

                try {
                    await download(
                        this.getAttribute('data-id'), 
                        this.getAttribute('data-type'), 
                        this.getAttribute('data-title'), 
                        this.getAttribute('data-artist')
                    );
                    this.innerHTML = "✔️"; 
                } catch (err) {
                    this.disabled = false;
                    this.innerHTML = originalContent;
                }
            });

            list.appendChild(card);
        });
        updateSongCount("songCountDisplay",data.length, icontype, "songs_found");
    } catch (err) {
    if (typeof showStatus === 'function') {
        showStatus(`${t('status_search_failed')} ${err}.`);
    }
}
}



async function download(id, type, title, artist) {
   message = `${t('status_downloading')} ${title} - ${artist}`;
   showStatus(message);

    try {
        const response = await fetch("/api/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ 
                id: id, 
                type: type, 
                title: title, 
                artist: artist,
                user: localStorage.getItem('karaoke_name') || 'Guest' 
            }),
        });

        const result = await response.json();
        console.log(result);
        if (result.success) {
            message = `${result.title} - ${result.artist} ${t('status_downloaded')}. ${result.lyrics_status}`;
            showStatus(message);
        } else {
            showStatus(`${t('status_download_error')}: ${result.message}`);
            throw err;
        }
    } catch (err) {
            message = `${result.title} - ${result.artist} ${t('status_not_downloaded')}`;
            showStatus(message);
        throw err;
    }
}