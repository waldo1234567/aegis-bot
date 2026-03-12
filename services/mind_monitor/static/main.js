document.addEventListener('DOMContentLoaded', () => {
    const API_ENDPOINT = '/api/state';
    const POLLING_INTERVAL = 2000; // 2 seconds

    // Cache DOM elements for performance
    const elements = {
        statusIndicator: document.getElementById('status-indicator'),
        systemStatus: document.getElementById('system-status'),
        valenceValue: document.getElementById('valence-value'),
        valenceBar: document.getElementById('valence-bar'),
        arousalValue: document.getElementById('arousal-value'),
        arousalBar: document.getElementById('arousal-bar'),
        dominanceValue: document.getElementById('dominance-value'),
        dominanceBar: document.getElementById('dominance-bar'),
        currentInvestigation: document.getElementById('current-investigation'),
        obsessionDepth: document.getElementById('obsession-depth'),
        memoryLog: document.getElementById('memory-log'),
    };

    function updateVAD(key, value) {
        const numValue = parseFloat(value).toFixed(2);
        elements[`${key}Value`].textContent = numValue;
        elements[`${key}Bar`].style.width = `${numValue * 100}%`;
    }

    function updateUI(state) {
        if (!state) return;

        // System Status
        const status = state.is_researching ? 'RESEARCHING' : 'IDLE';
        elements.systemStatus.textContent = status;
        elements.statusIndicator.className = `status-indicator status-${status.toLowerCase()}`;

        // VAD State
        if (state.current_vad) {
            updateVAD('valence', state.current_vad.valence || 0.5);
            updateVAD('arousal', state.current_vad.arousal || 0.5);
            updateVAD('dominance', state.current_vad.dominance || 0.5);
        }

        // Cognitive Process
        elements.currentInvestigation.textContent = state.current_investigation || '[ No active investigation ]';
        elements.obsessionDepth.textContent = state.obsession_stack ? state.obsession_stack.length : 0;

        // Memory Log (Example - assuming state provides this)
        if (state.memory_events && state.memory_events.length > 0) {
            elements.memoryLog.innerHTML = ''; // Clear old logs
            state.memory_events.forEach(event => {
                const li = document.createElement('li');
                li.textContent = `[${event.timestamp}] ${event.source}: ${event.summary}`;
                elements.memoryLog.appendChild(li);
            });
        }
    }

    async function fetchState() {
        try {
            const response = await fetch(API_ENDPOINT);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const state = await response.json();
            updateUI(state);
        } catch (error) {
            console.error('Failed to fetch Aegis state:', error);
            elements.systemStatus.textContent = 'DISCONNECTED';
            elements.statusIndicator.className = 'status-indicator status-disconnected'; // Assumes a 'disconnected' style is defined
        }
    }

    // Initial fetch and start polling
    fetchState();
    setInterval(fetchState, POLLING_INTERVAL);
});