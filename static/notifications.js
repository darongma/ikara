// 1. Create a container for the toasts if it doesn't exist
function getToastContainer(bottom = "90px", left = "50%") {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        Object.assign(container.style, {
            position: 'fixed',
            bottom: bottom,
            left: left,
            transform: 'translateX(-50%)',
            width: '90%',
            maxWidth: '380px',
            zIndex: '10000',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center', // Prevents the toast from stretching to 100% width
            gap: '10px',
            pointerEvents: 'none'
        });
        document.body.appendChild(container);
    }
    return container;
}

function showStatus(message, bottom = "90px", left = "50%") {
    const container = getToastContainer(bottom, left);
    const toast = document.createElement('div');

    const cleanMessage = message.replace(/\\'/g, "'").replace(/\\"/g, '"');
    toast.textContent = cleanMessage;

    // Style the individual toast
    Object.assign(toast.style, {
        background: 'rgba(0, 0, 0, 0.6)',
        color: '#1db954',
        padding: '12px 20px',
        borderRadius: '8px', // Restored to your original specification
        fontSize: '14px',
        fontWeight: 'bold',
        width: 'fit-content', // Only as wide as the message
        maxWidth: '100%',
        opacity: '0', 
        transition: 'opacity 1s ease-in-out', // Fast 1s fade-in
        border: '1px solid #1db954',
        textAlign: 'left',
        boxSizing: 'border-box',
        pointerEvents: 'auto',
        boxShadow: '0 4px 15px rgba(0,0,0,0.5)'
    });

    container.appendChild(toast);

    // Trigger Fade-in
    requestAnimationFrame(() => {
        toast.style.opacity = '1';
    });



    // Fade out and remove
    setTimeout(() => {
        // Change transition speed for a longer fade-out
        toast.style.transition = 'opacity 1s ease-in-out'; 
        toast.style.opacity = '0';
        
        setTimeout(() => {
            toast.remove();
            if (container.childNodes.length === 0) {
                container.remove();
            }
        }, 1000); // Wait for the 2.5s transition to finish
    }, 3000); // Time visible at full opacity
}

function t(key, data = {}) {
    let text = window.I18N?.[key] || key;

    // 1. Variable replacement
    Object.keys(data).forEach(placeholder => {
        text = text.replace(`{${placeholder}}`, data[placeholder]);
    });

    // 2. Auto-Pluralize if language is English
    if (data.count !== undefined && Number(data.count) !== 1) {
        // Use the global variable we set in the script tag
        const activeLang = window.I18N_LANG || 'en';
        
        if (activeLang === 'en') {
            // regex to find common karaoke words
            text = text.replace(/\b(song|result|item|file|user|request)\b/gi, '$1s');
        }
    }

    return text;
}



function updateSongCount(id, count, type, translate_id) {
    const display = document.getElementById(id);
    if (display) {
        if (count > 0) {
            display.innerText = `${t(translate_id, { count: count })} (${type})`;
        }
        else {
            display.innerText = "";
        }
    }
}
