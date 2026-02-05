document.addEventListener('DOMContentLoaded', async () => {
    // --- State ---
    const state = {
        browsingPath: "",
        inputFolder: "",
        frameRange: { start: 0, end: 0 },
        isConverting: false
    };

    // --- DOM Elements ---
    const dom = {
        inputFolder: document.getElementById('input_folder'),
        browseBtn: document.getElementById('browse-btn'),
        filenamePattern: document.getElementById('filename_pattern'),
        detectedRange: document.getElementById('detected-range'),
        sourceFps: document.getElementById('source_frame_rate'),

        codec: document.getElementById('codec'),
        outputFps: document.getElementById('frame_rate'),
        mp4Bitrate: document.getElementById('mp4_bitrate'),
        proresQscale: document.getElementById('prores_qscale'),
        desiredDuration: document.getElementById('desired_duration'),
        audioOption: document.getElementById('audio_option'),

        outputFolder: document.getElementById('output_folder'),
        outputFilename: document.getElementById('output_filename'),

        runBtn: document.getElementById('run-btn'),
        stopBtn: document.getElementById('stop-btn'),
        progressBar: document.getElementById('progress-bar'),
        logContainer: document.getElementById('log-container'),
        statusIndicator: document.getElementById('status-indicator'),

        // Modal
        modal: document.getElementById('file-browser-modal'),
        closeModal: document.getElementById('close-modal'),
        navUp: document.getElementById('nav-up'),
        browserPath: document.getElementById('browser-path'),
        fileList: document.getElementById('file-list'),
        selectFolderBtn: document.getElementById('select-folder-btn'),

        codecOptions: document.querySelectorAll('.codec-option')
    };

    // --- Initialization ---
    async function init() {
        log("Use 'Browse' to select an input sequence folder.", "info");
        await loadSettings();
        setupWebSocket();
    }

    // --- WebSockets ---
    function setupWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(`${protocol}://${window.location.host}/ws/status`);

        ws.onopen = () => {
            dom.statusIndicator.textContent = "Connected";
            dom.statusIndicator.className = "log-success";
        };

        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            handleWsMessage(msg);
        };

        ws.onclose = () => {
            dom.statusIndicator.textContent = "Disconnected";
            dom.statusIndicator.className = "log-error";
            setTimeout(setupWebSocket, 3000); // Reconnect
        };
    }

    function handleWsMessage(msg) {
        if (msg.type === 'output' || msg.type === 'error') {
            log(msg.content, msg.type);
        } else if (msg.type === 'progress') {
            const pct = parseFloat(msg.content);
            if (!isNaN(pct)) {
                dom.progressBar.style.width = `${pct}%`;
            }
        } else if (msg.type === 'job_status') {
            if (msg.content === 'idle') {
                setConvertingState(false);
            }
        } else if (msg.type === 'success') {
            log(msg.content, 'success');
            setConvertingState(false);
        } else if (msg.type === 'cancelled') {
            log(msg.content, 'error');
            setConvertingState(false);
        }
    }

    function setConvertingState(isConverting) {
        state.isConverting = isConverting;
        dom.runBtn.disabled = isConverting;
        dom.stopBtn.disabled = !isConverting;
        dom.inputFolder.readOnly = isConverting;

        if (isConverting) {
            dom.statusIndicator.textContent = "Processing...";
            dom.statusIndicator.className = "log-info";
            dom.stopBtn.style.opacity = 1;
        } else {
            dom.statusIndicator.textContent = "Ready";
            dom.statusIndicator.className = "log-success";
            dom.progressBar.style.width = '0%';
        }
    }

    // --- Settings & UI Logic ---
    async function loadSettings() {
        try {
            const settings = await API.getSettings();
            // Apply defaults if fields are empty
            if (settings.last_input_folder) state.inputFolder = settings.last_input_folder;
            if (settings.last_output_folder) dom.outputFolder.value = settings.last_output_folder;

            // Set input values
            if (dom.inputFolder.value === "") dom.inputFolder.value = settings.last_input_folder || "";
            if (dom.outputFolder.value === "") dom.outputFolder.value = settings.last_output_folder || "";

            dom.sourceFps.value = settings.source_frame_rate || "24";
            dom.outputFps.value = settings.frame_rate || "24";
            dom.desiredDuration.value = settings.desired_duration || "15";
            dom.mp4Bitrate.value = settings.mp4_bitrate || "30";
            dom.proresQscale.value = settings.prores_qscale || "9";

            if (settings.codec) {
                dom.codec.value = settings.codec;
                updateCodecOptions();
            }
        } catch (e) {
            console.error("Failed to load settings", e);
        }
    }

    async function saveCurrentSettings() {
        const settings = {
            last_input_folder: dom.inputFolder.value,
            last_output_folder: dom.outputFolder.value,
            frame_rate: dom.outputFps.value,
            source_frame_rate: dom.sourceFps.value,
            desired_duration: dom.desiredDuration.value,
            codec: dom.codec.value,
            mp4_bitrate: dom.mp4Bitrate.value,
            prores_qscale: dom.proresQscale.value
        };
        await API.saveSettings(settings);
    }

    function updateCodecOptions() {
        const codec = dom.codec.value;
        dom.codecOptions.forEach(el => el.classList.add('hidden'));

        if (codec === 'h264' || codec === 'h265') {
            document.querySelector('.show-mp4').classList.remove('hidden');
            dom.outputFilename.value = dom.outputFilename.value.replace(/\.\w+$/, '.mp4');
        } else if (codec.startsWith('prores')) {
            document.querySelector('.show-prores').classList.remove('hidden');
            dom.outputFilename.value = dom.outputFilename.value.replace(/\.\w+$/, '.mov');
        } else {
            dom.outputFilename.value = dom.outputFilename.value.replace(/\.\w+$/, '.mov');
        }
    }

    // --- File Browser ---
    async function openFileBrowser(startPath) {
        state.browsingPath = startPath || dom.inputFolder.value || ".";
        await refreshBrowser();
        dom.modal.style.display = 'flex';
    }

    async function refreshBrowser() {
        dom.fileList.innerHTML = '<li class="file-item">Loading...</li>';
        try {
            const data = await API.browse(state.browsingPath);
            state.browsingPath = data.current_path;
            dom.browserPath.value = data.current_path;

            dom.fileList.innerHTML = '';

            if (data.items.length === 0) {
                dom.fileList.innerHTML = '<li class="file-item" style="color: grey;">Empty directory</li>';
                return;
            }

            data.items.forEach(item => {
                const li = document.createElement('li');
                li.className = 'file-item';
                li.innerHTML = `
                    <span class="file-icon">${item.is_dir ? '📁' : '📄'}</span>
                    <span>${item.name}</span>
                `;
                li.onclick = () => {
                    if (item.is_dir) {
                        state.browsingPath = item.path;
                        refreshBrowser();
                    }
                };
                dom.fileList.appendChild(li);
            });
        } catch (e) {
            dom.fileList.innerHTML = `<li class="file-item log-error">Error: ${e.message}</li>`;
        }
    }

    async function handleFolderSelection() {
        const selectedPath = state.browsingPath;
        dom.inputFolder.value = selectedPath;
        dom.modal.style.display = 'none';

        // Auto-set output folder to parent of input
        // Using basic string manipulation for path
        const parent = selectedPath.split('/').slice(0, -1).join('/');
        dom.outputFolder.value = parent || selectedPath;

        // Scan for sequences
        await scanForSequences(selectedPath);
        saveCurrentSettings();
    }

    async function scanForSequences(path) {
        log(`Scanning for sequences in: ${path}...`, 'info');
        try {
            const sequences = await API.scan(path);
            if (sequences.length === 0) {
                log("No image sequences detected.", 'error');
                dom.filenamePattern.value = "";
                dom.detectedRange.textContent = "None";
                return;
            }

            // Default to first found sequence
            const seq = sequences[0];
            dom.filenamePattern.value = seq.pattern;
            state.frameRange = { start: seq.start, end: seq.end };
            dom.detectedRange.textContent = seq.range_string;

            // Auto-set output filename
            const seqName = seq.head.replace(/[._]$/, "");
            const ext = dom.outputFilename.value.match(/\.\w+$/)[0];
            dom.outputFilename.value = `${seqName}${ext}`;

            log(`Detected sequence: ${seq.pattern} ${seq.range_string}`, 'success');

        } catch (e) {
            log(`Scan failed: ${e.message}`, 'error');
        }
    }

    // --- Logging ---
    function log(msg, type = 'output') {
        const div = document.createElement('div');
        div.className = `log-entry log-${type}`;
        div.textContent = msg; // Text content prevents XSS
        dom.logContainer.appendChild(div);
        dom.logContainer.scrollTop = dom.logContainer.scrollHeight;
    }

    // --- Event Listeners ---
    dom.browseBtn.addEventListener('click', () => openFileBrowser(dom.inputFolder.value));
    dom.closeModal.addEventListener('click', () => dom.modal.style.display = 'none');
    dom.selectFolderBtn.addEventListener('click', handleFolderSelection);

    dom.navUp.addEventListener('click', () => {
        // Go up one level
        // Naive path manipulation, but usually fine for linux paths
        const parts = state.browsingPath.split('/').filter(p => p);
        if (parts.length > 0) {
            parts.pop();
            // Handle root
            const newPath = parts.length === 0 ? '/' : '/' + parts.join('/');
            state.browsingPath = newPath;
            refreshBrowser();
        }
    });

    dom.codec.addEventListener('change', updateCodecOptions);

    dom.runBtn.addEventListener('click', async () => {
        if (!dom.inputFolder.value || !dom.outputFolder.value) {
            alert("Please select input and output folders.");
            return;
        }

        const config = {
            input_folder: dom.inputFolder.value,
            filename_pattern: dom.filenamePattern.value,
            output_folder: dom.outputFolder.value,
            output_filename: dom.outputFilename.value,
            frame_rate: dom.outputFps.value,
            source_frame_rate: dom.sourceFps.value,
            desired_duration: dom.desiredDuration.value,
            codec: dom.codec.value,
            mp4_bitrate: dom.mp4Bitrate.value,
            prores_profile: dom.codec.value.startsWith('prores') ? dom.codec.value.replace('prores_', '') : "2",
            prores_qscale: dom.proresQscale.value,
            audio_option: dom.audioOption.value,
            start_frame: state.frameRange.start,
            end_frame: state.frameRange.end
        };

        if (dom.codec.value.startsWith('prores')) {
            // Map dropdown value to profile index logic if needed
            // Simple mapping based on value names
            if (config.prores_profile === '422') config.prores_profile = '2';
            if (config.prores_profile === '422_lt') config.prores_profile = '1';
            if (config.prores_profile === '444') config.prores_profile = '4';
        }

        setConvertingState(true);
        dom.logContainer.innerHTML = ''; // Clear logs
        log("Starting job...", "info");
        await saveCurrentSettings();

        try {
            await API.startConversion(config);
        } catch (e) {
            log(`Failed to start job: ${e.message}`, 'error');
            setConvertingState(false);
        }
    });

    dom.stopBtn.addEventListener('click', async () => {
        await API.cancelConversion();
    });

    // Run init
    init();
});
