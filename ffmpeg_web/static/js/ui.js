document.addEventListener('DOMContentLoaded', async () => {
    // --- State ---
    const state = {
        browsingPath: "",
        inputFolder: "",
        frameRange: { start: 0, end: 0 },
        sourceRes: { width: null, height: null },
        filenameCustom: false,
        isConverting: false,
        transformCustom: false,
        rawBrowserItems: [],
        autoScrollLogs: true,
        activeLogFilter: 'all'
    };

    // --- DOM Elements ---
    const dom = {
        inputFolder: document.getElementById('input_folder'),
        browseBtn: document.getElementById('browse-btn'),
        filenamePattern: document.getElementById('filename_pattern'),
        detectedRange: document.getElementById('detected-range'),
        detectedFrames: document.getElementById('detected-frames'),
        detectedRes: document.getElementById('detected-res'),
        detectedDuration: document.getElementById('detected-duration'),
        sequenceFormatBadge: document.getElementById('sequence-format-badge'),
        sourceFps: document.getElementById('source_frame_rate'),

        codec: document.getElementById('codec'),
        outputFps: document.getElementById('frame_rate'),
        mp4Bitrate: document.getElementById('mp4_bitrate'),
        h264Level: document.getElementById('h264_level'),
        proresQscale: document.getElementById('prores_qscale'),
        outputTransform: document.getElementById('output_transform'),
        codecInfo: document.getElementById('codec_info'),
        versionBanner: document.getElementById('version_banner'),
        desiredDuration: document.getElementById('desired_duration'),
        audioOption: document.getElementById('audio_option'),

        reformatEnabled: document.getElementById('reformat_enabled'),
        reformatFields: document.getElementById('reformat-fields'),
        reformatWidth: document.getElementById('reformat_width'),
        reformatHeight: document.getElementById('reformat_height'),
        reformatHint: document.getElementById('reformat-hint'),

        outputFolder: document.getElementById('output_folder'),
        outputFilename: document.getElementById('output_filename'),

        runBtn: document.getElementById('run-btn'),
        stopBtn: document.getElementById('stop-btn'),
        progressBar: document.getElementById('progress-bar'),
        progressPhaseText: document.getElementById('progress-phase-text'),
        progressPercentText: document.getElementById('progress-percent-text'),
        phaseBadge: document.getElementById('phase-badge'),
        logContainer: document.getElementById('log-container'),
        statusIndicator: document.getElementById('status-indicator'),
        statusPill: document.getElementById('status-pill'),
        depsWarning: document.getElementById('deps-warning'),

        // Console Controls
        consoleTabs: document.querySelectorAll('.console-tabs .tab-btn'),
        autoscrollBtn: document.getElementById('autoscroll-btn'),
        copyLogBtn: document.getElementById('copy-log-btn'),
        clearLogBtn: document.getElementById('clear-log-btn'),

        // Modal
        modal: document.getElementById('file-browser-modal'),
        closeModal: document.getElementById('close-modal'),
        navUp: document.getElementById('nav-up'),
        browserBreadcrumbs: document.getElementById('browser-breadcrumbs'),
        browserSearch: document.getElementById('browser-search'),
        browserPath: document.getElementById('browser-path'),
        fileList: document.getElementById('file-list'),
        selectFolderBtn: document.getElementById('select-folder-btn'),

        codecOptions: document.querySelectorAll('.codec-option'),
        toastContainer: document.getElementById('toast-container')
    };

    // --- Toast Notification System ---
    function showToast(title, message = '', type = 'info', duration = 4000) {
        if (!dom.toastContainer) return;

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;

        const icons = {
            info: 'ℹ️',
            success: '✅',
            warning: '⚠️',
            error: '🛑'
        };

        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
            <div class="toast-content">
                <div class="toast-title">${title}</div>
                ${message ? `<div class="toast-message">${message}</div>` : ''}
            </div>
            <button type="button" class="toast-close" aria-label="Close">✕</button>
        `;

        const closeBtn = toast.querySelector('.toast-close');
        const dismiss = () => {
            toast.classList.add('toast-hiding');
            setTimeout(() => toast.remove(), 200);
        };

        closeBtn.addEventListener('click', dismiss);
        dom.toastContainer.appendChild(toast);

        if (duration > 0) {
            setTimeout(dismiss, duration);
        }
    }

    // --- Initialization ---
    async function init() {
        log("BCN FFMpeg Converter ready. Use 'Browse' to load a sequence.", "info");
        await loadSettings();
        setupWebSocket();
        await checkDependencies();
        await loadCodecInfo();
        checkVersion();
        
        // Cheap poll plus a check whenever the tab regains focus, so a
        // deploy that happens while this page is open is noticed.
        setInterval(checkVersion, 30000);
        window.addEventListener('focus', checkVersion);
    }

    // --- WebSockets ---
    function setupWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(`${protocol}://${window.location.host}/ws/status`);

        ws.onopen = () => {
            updateConnectionStatus(true);
        };

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                handleWsMessage(msg);
            } catch (err) {
                console.error("Error parsing websocket message:", err);
            }
        };

        ws.onclose = () => {
            updateConnectionStatus(false);
            setTimeout(setupWebSocket, 3000); // Reconnect
        };
    }

    function updateConnectionStatus(connected) {
        if (connected) {
            dom.statusIndicator.textContent = state.isConverting ? "Processing..." : "Ready";
            dom.statusPill.className = state.isConverting ? "status-pill status-processing" : "status-pill status-ready";
        } else {
            dom.statusIndicator.textContent = "Disconnected";
            dom.statusPill.className = "status-pill status-error";
        }
    }

    function handleWsMessage(msg) {
        if (msg.type === 'output' || msg.type === 'error') {
            log(msg.content, msg.type);

            // Detect phase changes from backend log messages
            if (msg.content.includes("Starting EXR Conversion Phase")) {
                updatePhase("EXR Pre-pass (oiiotool)", "badge-info");
            } else if (msg.content.includes("EXR Phase Complete") || msg.content.includes("Proceeding to FFmpeg video encoding") || msg.content.includes("Starting FFmpeg process")) {
                updatePhase("FFmpeg Encoding", "badge-info");
            }
        } else if (msg.type === 'progress') {
            const pct = parseFloat(msg.content);
            if (!isNaN(pct)) {
                const formattedPct = Math.min(Math.max(pct, 0), 100);
                dom.progressBar.style.width = `${formattedPct}%`;
                if (dom.progressPercentText) {
                    dom.progressPercentText.textContent = `${Math.round(formattedPct)}%`;
                }
            }
        } else if (msg.type === 'job_status') {
            if (msg.content === 'idle') {
                setConvertingState(false);
                updatePhase("Idle", "badge-neutral");
            }
        } else if (msg.type === 'success') {
            log(msg.content, 'success');
            showToast("Conversion Succeeded", msg.content, "success");
            setConvertingState(false);
            updatePhase("Complete", "badge-success");
            if (dom.progressPercentText) dom.progressPercentText.textContent = "100%";
            dom.progressBar.style.width = '100%';
        } else if (msg.type === 'cancelled') {
            log(msg.content, 'error');
            showToast("Conversion Cancelled", "Job was cancelled by user.", "warning");
            setConvertingState(false);
            updatePhase("Cancelled", "badge-neutral");
        }
    }

    function updatePhase(phaseName, badgeClass = "badge-info") {
        if (dom.phaseBadge) {
            dom.phaseBadge.textContent = phaseName;
            dom.phaseBadge.className = `badge ${badgeClass}`;
        }
        if (dom.progressPhaseText) {
            dom.progressPhaseText.textContent = phaseName;
        }
    }

    function setConvertingState(isConverting) {
        state.isConverting = isConverting;
        dom.runBtn.disabled = isConverting;
        dom.stopBtn.disabled = !isConverting;
        dom.inputFolder.readOnly = isConverting;

        if (isConverting) {
            dom.statusIndicator.textContent = "Processing...";
            dom.statusPill.className = "status-pill status-processing";
            updatePhase("Processing...", "badge-info");
        } else {
            dom.statusIndicator.textContent = "Ready";
            dom.statusPill.className = "status-pill status-ready";
            if (!dom.phaseBadge || dom.phaseBadge.textContent === "Processing...") {
                updatePhase("Idle", "badge-neutral");
            }
        }
    }

    // --- Settings & UI Logic ---
    async function loadSettings() {
        try {
            const settings = await API.getSettings();
            if (settings.last_input_folder) state.inputFolder = settings.last_input_folder;
            if (settings.last_output_folder) dom.outputFolder.value = settings.last_output_folder;

            if (dom.inputFolder.value === "") dom.inputFolder.value = settings.last_input_folder || "";
            if (dom.outputFolder.value === "") dom.outputFolder.value = settings.last_output_folder || "";

            dom.sourceFps.value = settings.source_frame_rate || "24";
            dom.outputFps.value = settings.frame_rate || "24";
            dom.desiredDuration.value = settings.desired_duration || "15";
            dom.mp4Bitrate.value = settings.mp4_bitrate || "30";
            dom.h264Level.value = settings.level || "6.1";
            dom.proresQscale.value = settings.prores_qscale || "9";
            if (settings.output_transform) {
                dom.outputTransform.value = settings.output_transform;
            }
            state.transformCustom = Boolean(settings.output_transform_custom);

            dom.reformatEnabled.checked = Boolean(settings.reformat_enabled);
            dom.reformatWidth.value = settings.reformat_width || "";
            dom.reformatHeight.value = settings.reformat_height || "";

            if (settings.output_filename) {
                dom.outputFilename.value = settings.output_filename;
            }
            state.filenameCustom = Boolean(settings.output_filename_custom);
            updateReformatUI();

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
            level: dom.h264Level.value,
            prores_qscale: dom.proresQscale.value,
            output_transform: dom.outputTransform.value,
            output_filename: dom.outputFilename.value,
            output_filename_custom: state.filenameCustom,
            output_transform_custom: state.transformCustom,
            reformat_enabled: dom.reformatEnabled.checked,
            reformat_width: dom.reformatWidth.value,
            reformat_height: dom.reformatHeight.value
        };
        await API.saveSettings(settings);
    }

    // --- Reformat Calculations ---
    function evenUp(value) {
        const rounded = Math.round(value);
        if (rounded < 2) return 2;
        return rounded + (rounded % 2);
    }

    function parseDimension(field) {
        const raw = field.value.trim();
        if (raw === "") return null;
        const value = parseInt(raw, 10);
        return Number.isFinite(value) ? value : NaN;
    }

    function resolveDimensions(reqW, reqH, srcW, srcH) {
        if (Number.isNaN(reqW) || Number.isNaN(reqH)) {
            return { error: "Width and height must be whole numbers." };
        }
        if ((reqW !== null && reqW <= 0) || (reqH !== null && reqH <= 0)) {
            return { error: "Width and height must be positive numbers." };
        }
        if (reqW === null && reqH === null) {
            return { error: "Enter a width, a height, or both." };
        }
        if (reqW !== null && reqH !== null) {
            return { width: evenUp(reqW), height: evenUp(reqH) };
        }
        if (!srcW || !srcH) {
            return { unknownSource: true };
        }
        if (reqW !== null) {
            return { width: evenUp(reqW), height: evenUp(reqW * srcH / srcW) };
        }
        return { width: evenUp(reqH * srcW / srcH), height: evenUp(reqH) };
    }

    function updateReformatUI() {
        const enabled = dom.reformatEnabled.checked;
        dom.reformatFields.classList.toggle('hidden', !enabled);
        if (!enabled) return;

        const reqW = parseDimension(dom.reformatWidth);
        const reqH = parseDimension(dom.reformatHeight);
        const { width: srcW, height: srcH } = state.sourceRes;
        const result = resolveDimensions(reqW, reqH, srcW, srcH);

        dom.reformatHint.classList.remove('is-error');

        if (result.error) {
            dom.reformatHint.classList.add('is-error');
            dom.reformatHint.textContent = result.error;
            return;
        }

        if (result.unknownSource) {
            dom.reformatHint.textContent =
                "Source resolution unknown \u2014 the missing dimension will be " +
                "derived from the source aspect ratio at conversion time.";
            return;
        }

        const source = (srcW && srcH) ? `Source: ${srcW} \u00d7 ${srcH} \u2192 ` : "";
        dom.reformatHint.innerHTML =
            `${source}Output: <strong>${result.width} \u00d7 ${result.height}</strong>`;

        const snapped = (reqW !== null && reqW !== result.width)
            || (reqH !== null && reqH !== result.height);
        if (snapped) {
            dom.reformatHint.innerHTML +=
                " \u2014 rounded up to even (required for 4:2:0 chroma).";
        }
    }

    function defaultTransformForCodec(codec) {
        return codec.startsWith('prores') ? 'Output - Rec.709' : 'Output - sRGB';
    }

    function updateCodecOptions() {
        const codec = dom.codec.value;
        if (!state.transformCustom) {
            dom.outputTransform.value = defaultTransformForCodec(codec);
        }
        dom.codecOptions.forEach(el => el.classList.add('hidden'));

        if (codec === 'h264' || codec === 'h265' || codec === 'h264_h10') {
            document.querySelector('.show-mp4').classList.remove('hidden');
            // H.265 is excluded: libx265 has no -level option, so the
            // backend declares none and the control would be a lie.
            if (codec === 'h264' || codec === 'h264_h10') {
                document.querySelector('.show-h264-level').classList.remove('hidden');
            }
            dom.outputFilename.value = dom.outputFilename.value.replace(/\.\w+$/, '.mp4');
        } else if (codec.startsWith('prores')) {
            document.querySelector('.show-prores').classList.remove('hidden');
            dom.outputFilename.value = dom.outputFilename.value.replace(/\.\w+$/, '.mov');
        } else {
            dom.outputFilename.value = dom.outputFilename.value.replace(/\.\w+$/, '.mov');
        }
    }

    async function checkDependencies() {
        try {
            const status = await API.getDeps();
            if (!status.ok) {
                const issues = Array.isArray(status.issues) ? status.issues.join(' ') : 'Dependency issues detected.';
                if (dom.depsWarning) {
                    dom.depsWarning.textContent = issues;
                    dom.depsWarning.classList.remove('hidden');
                }
                dom.runBtn.disabled = true;
                log(`Dependencies warning: ${issues}`, 'error');
            } else if (dom.depsWarning) {
                dom.depsWarning.textContent = '';
                dom.depsWarning.classList.add('hidden');
                dom.runBtn.disabled = state.isConverting;
            }
        } catch (e) {
            log(`Failed to query dependency status: ${e.message}`, 'error');
        }
    }

    // --- File Browser & Breadcrumbs ---
    async function openFileBrowser(startPath) {
        state.browsingPath = startPath || dom.inputFolder.value || ".";
        dom.modal.style.display = 'flex';
        await refreshBrowser();
    }

    function renderBreadcrumbs(currentPath) {
        if (!dom.browserBreadcrumbs) return;
        dom.browserBreadcrumbs.innerHTML = '';

        const normalized = currentPath.startsWith('/') ? currentPath : '/' + currentPath;
        const parts = normalized.split('/').filter(Boolean);

        // Root crumb
        const rootCrumb = document.createElement('span');
        rootCrumb.className = 'crumb-segment';
        rootCrumb.textContent = '/';
        rootCrumb.onclick = () => {
            state.browsingPath = '/';
            refreshBrowser();
        };
        dom.browserBreadcrumbs.appendChild(rootCrumb);

        let accumulated = '';
        parts.forEach((part, index) => {
            const sep = document.createElement('span');
            sep.className = 'crumb-separator';
            sep.textContent = '/';
            dom.browserBreadcrumbs.appendChild(sep);

            accumulated += '/' + part;
            const crumb = document.createElement('span');
            crumb.className = 'crumb-segment';
            crumb.textContent = part;
            const targetPath = accumulated;
            crumb.onclick = () => {
                state.browsingPath = targetPath;
                refreshBrowser();
            };
            dom.browserBreadcrumbs.appendChild(crumb);
        });

        // Scroll breadcrumbs to end
        dom.browserBreadcrumbs.scrollLeft = dom.browserBreadcrumbs.scrollWidth;
    }

    async function refreshBrowser() {
        dom.fileList.innerHTML = '<li class="file-item"><div class="file-item-main"><span class="file-item-name">Loading directory contents...</span></div></li>';
        try {
            const data = await API.browse(state.browsingPath);
            state.browsingPath = data.current_path;
            dom.browserPath.value = data.current_path;
            renderBreadcrumbs(data.current_path);

            state.rawBrowserItems = data.items || [];
            applyBrowserFilter();
        } catch (e) {
            dom.fileList.innerHTML = `<li class="file-item"><div class="file-item-main"><span class="file-item-name log-error">Error: ${e.message}</span></div></li>`;
        }
    }

    function getFileIconAndTag(name, isDir) {
        if (isDir) {
            return { icon: '📁', tag: 'DIR' };
        }
        const lower = name.toLowerCase();
        if (lower.endsWith('.exr')) {
            return { icon: '🎞️', tag: 'EXR' };
        }
        if (lower.endsWith('.mov') || lower.endsWith('.mp4') || lower.endsWith('.mkv')) {
            return { icon: '🎬', tag: 'VIDEO' };
        }
        if (lower.endsWith('.png') || lower.endsWith('.jpg') || lower.endsWith('.jpeg') || lower.endsWith('.tiff') || lower.endsWith('.tif') || lower.endsWith('.dpx')) {
            return { icon: '🖼️', tag: 'IMAGE' };
        }
        return { icon: '📄', tag: 'FILE' };
    }

    function applyBrowserFilter() {
        const query = (dom.browserSearch ? dom.browserSearch.value.trim().toLowerCase() : '');
        const items = state.rawBrowserItems.filter(item => {
            if (!query) return true;
            return item.name.toLowerCase().includes(query);
        });

        dom.fileList.innerHTML = '';

        if (items.length === 0) {
            dom.fileList.innerHTML = '<li class="file-item"><div class="file-item-main"><span class="file-item-name" style="color: var(--text-muted);">No matching items found</span></div></li>';
            return;
        }

        items.forEach(item => {
            const li = document.createElement('li');
            li.className = 'file-item';
            const { icon, tag } = getFileIconAndTag(item.name, item.is_dir);

            li.innerHTML = `
                <div class="file-item-main">
                    <span class="file-item-icon">${icon}</span>
                    <span class="file-item-name" title="${item.name}">${item.name}</span>
                </div>
                <span class="file-item-tag">${tag}</span>
            `;

            li.onclick = () => {
                if (item.is_dir) {
                    state.browsingPath = item.path;
                    if (dom.browserSearch) dom.browserSearch.value = '';
                    refreshBrowser();
                } else {
                    handleFrameSelection(item.path);
                }
            };

            if (!item.is_dir) {
                li.title = "Click to select this sequence";
            }
            dom.fileList.appendChild(li);
        });
    }

    function getParentPath(path) {
        const parts = String(path).split('/').filter(Boolean);
        parts.pop();
        return parts.length ? '/' + parts.join('/') : '/';
    }

    async function handleFrameSelection(framePath) {
        const folder = getParentPath(framePath);
        dom.inputFolder.value = folder;
        if (!dom.outputFolder.value) {
            dom.outputFolder.value = getParentPath(folder);
        }
        dom.modal.style.display = 'none';
        showToast("Sequence Selected", `Probing sequence in ${folder}...`, "info", 2500);
        await scanForSequences(framePath);
        saveCurrentSettings();
    }

    async function handleFolderSelection() {
        const selectedPath = state.browsingPath;
        dom.inputFolder.value = selectedPath;
        dom.modal.style.display = 'none';

        const parent = getParentPath(selectedPath);
        dom.outputFolder.value = parent || selectedPath;

        showToast("Folder Selected", `Scanning ${selectedPath}...`, "info", 2500);
        await scanForSequences(selectedPath);
        saveCurrentSettings();
    }

    function updateSequenceSummaryCard(seq) {
        if (!seq) {
            if (dom.detectedRange) dom.detectedRange.textContent = "None";
            if (dom.detectedFrames) dom.detectedFrames.textContent = "-";
            if (dom.detectedRes) dom.detectedRes.textContent = "-";
            if (dom.detectedDuration) dom.detectedDuration.textContent = "-";
            if (dom.sequenceFormatBadge) {
                dom.sequenceFormatBadge.textContent = "No Sequence";
                dom.sequenceFormatBadge.className = "badge badge-neutral";
            }
            return;
        }

        const totalFrames = (seq.end !== undefined && seq.start !== undefined) 
            ? (seq.end - seq.start + 1) 
            : (seq.count || 0);

        if (dom.detectedRange) dom.detectedRange.textContent = seq.range_string || `${seq.start}-${seq.end}`;
        if (dom.detectedFrames) dom.detectedFrames.textContent = `${totalFrames} frames`;
        
        if (dom.detectedRes) {
            if (seq.width && seq.height) {
                dom.detectedRes.textContent = `${seq.width} \u00d7 ${seq.height}`;
            } else {
                dom.detectedRes.textContent = "Auto / Unknown";
            }
        }

        const fps = parseFloat(dom.sourceFps.value) || 24;
        const nativeSecs = totalFrames > 0 ? (totalFrames / fps).toFixed(2) : "0.00";
        if (dom.detectedDuration) dom.detectedDuration.textContent = `${nativeSecs}s (@ ${fps}fps)`;

        if (dom.sequenceFormatBadge) {
            const isExr = (seq.pattern || "").toLowerCase().endsWith('.exr');
            if (isExr) {
                dom.sequenceFormatBadge.textContent = "EXR (ACEScg)";
                dom.sequenceFormatBadge.className = "badge badge-info";
            } else {
                const ext = (seq.pattern || "").split('.').pop().toUpperCase();
                dom.sequenceFormatBadge.textContent = ext || "IMAGE SEQ";
                dom.sequenceFormatBadge.className = "badge badge-neutral";
            }
        }
    }

    async function scanForSequences(path) {
        log(`Scanning for sequences in: ${path}...`, 'info');
        try {
            const sequences = await API.scan(path);
            if (sequences.length === 0) {
                log("No image sequences detected.", 'error');
                dom.filenamePattern.value = "";
                state.sourceRes = { width: null, height: null };
                updateSequenceSummaryCard(null);
                updateReformatUI();
                showToast("No Sequence Found", "No image sequence detected in the selected folder.", "warning");
                return;
            }

            const seq = sequences[0];
            dom.filenamePattern.value = seq.pattern;
            state.frameRange = { start: seq.start, end: seq.end };
            state.sourceRes = { width: seq.width || null, height: seq.height || null };
            
            updateSequenceSummaryCard(seq);
            updateReformatUI();

            if (!state.filenameCustom) {
                const seqName = seq.head.replace(/[._]$/, "");
                const extMatch = dom.outputFilename.value.match(/\.\w+$/);
                dom.outputFilename.value = `${seqName}${extMatch ? extMatch[0] : ".mp4"}`;
            }

            log(`Detected sequence: ${seq.pattern} [${seq.range_string}]`, 'success');
            showToast("Sequence Ready", `${seq.pattern} (${seq.range_string})`, "success", 3000);

        } catch (e) {
            log(`Scan failed: ${e.message}`, 'error');
            showToast("Scan Error", e.message, "error");
        }
    }

    // --- Logging & Console Toolbar ---
    function log(msg, type = 'output') {
        const div = document.createElement('div');
        div.className = `log-entry log-${type}`;
        div.setAttribute('data-type', type);
        div.textContent = msg;

        // Apply active filter
        if (state.activeLogFilter !== 'all' && state.activeLogFilter !== type) {
            div.style.display = 'none';
        }

        dom.logContainer.appendChild(div);

        if (state.autoScrollLogs) {
            dom.logContainer.scrollTop = dom.logContainer.scrollHeight;
        }
    }

    function setLogFilter(filterType) {
        state.activeLogFilter = filterType;
        dom.consoleTabs.forEach(tab => {
            tab.classList.toggle('active', tab.getAttribute('data-filter') === filterType);
        });

        const entries = dom.logContainer.querySelectorAll('.log-entry');
        entries.forEach(entry => {
            const entryType = entry.getAttribute('data-type');
            if (filterType === 'all' || entryType === filterType) {
                entry.style.display = 'block';
            } else {
                entry.style.display = 'none';
            }
        });
    }

    // --- Event Listeners ---
    dom.browseBtn.addEventListener('click', () => openFileBrowser(dom.inputFolder.value));

    // Allow pasting or typing a path directly into the input folder field
    // Mirrors the extension filter in core/explorer.py. A pasted path ending
    // in one of these is a frame, not a folder.
    const MEDIA_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.exr', '.mov', '.mp4', '.tiff'];

    function looksLikeMediaFile(path) {
        const name = path.split('/').pop() || '';
        const dot = name.lastIndexOf('.');
        return dot > 0 && MEDIA_EXTENSIONS.includes(name.slice(dot).toLowerCase());
    }

    async function handleManualPathInput() {
        const raw = dom.inputFolder.value.trim();
        if (!raw) return;

        // Pasting a frame path is supported, but the field must end up holding
        // the folder: its value is persisted as last_input_folder, which seeds
        // the file browser on the next launch. Storing a file there makes
        // Browse fail until the user edits the field by hand. This mirrors
        // handleFrameSelection so a pasted frame behaves exactly like the same
        // frame picked in the browser.
        const isFrame = looksLikeMediaFile(raw);
        const folder = isFrame ? getParentPath(raw) : raw;

        // Auto-populate output folder if empty
        if (!dom.outputFolder.value) {
            dom.outputFolder.value = getParentPath(folder);
        }

        // Scan with the frame -- it tells the backend which sequence was meant
        // when a folder holds several -- but display and persist the folder.
        await scanForSequences(raw);
        if (isFrame) {
            dom.inputFolder.value = folder;
        }
        saveCurrentSettings();
    }

    dom.inputFolder.addEventListener('change', handleManualPathInput);
    dom.inputFolder.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            handleManualPathInput();
        }
    });

    dom.closeModal.addEventListener('click', () => dom.modal.style.display = 'none');
    
    // Close modal on backdrop click
    const backdrop = dom.modal.querySelector('.modal-backdrop');
    if (backdrop) {
        backdrop.addEventListener('click', () => dom.modal.style.display = 'none');
    }

    // Keyboard shortcuts
    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && dom.modal.style.display === 'flex') {
            dom.modal.style.display = 'none';
        }
    });

    dom.selectFolderBtn.addEventListener('click', handleFolderSelection);

    dom.navUp.addEventListener('click', () => {
        const parts = state.browsingPath.split('/').filter(p => p);
        if (parts.length > 0) {
            parts.pop();
            const newPath = parts.length === 0 ? '/' : '/' + parts.join('/');
            state.browsingPath = newPath;
            if (dom.browserSearch) dom.browserSearch.value = '';
            refreshBrowser();
        }
    });

    if (dom.browserSearch) {
        dom.browserSearch.addEventListener('input', applyBrowserFilter);
    }

    // Console tabs
    dom.consoleTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            setLogFilter(tab.getAttribute('data-filter'));
        });
    });

    // Auto-scroll toggle
    if (dom.autoscrollBtn) {
        dom.autoscrollBtn.addEventListener('click', () => {
            state.autoScrollLogs = !state.autoScrollLogs;
            dom.autoscrollBtn.classList.toggle('active', state.autoScrollLogs);
            if (state.autoScrollLogs) {
                dom.logContainer.scrollTop = dom.logContainer.scrollHeight;
            }
        });
    }

    // Copy logs
    if (dom.copyLogBtn) {
        dom.copyLogBtn.addEventListener('click', async () => {
            const text = Array.from(dom.logContainer.querySelectorAll('.log-entry'))
                .map(el => el.textContent)
                .join('');
            if (!text) {
                showToast("Console Empty", "No logs to copy.", "info");
                return;
            }
            try {
                await navigator.clipboard.writeText(text);
                showToast("Copied to Clipboard", "Console logs copied successfully.", "success", 2000);
            } catch (err) {
                showToast("Copy Failed", "Unable to access clipboard.", "error");
            }
        });
    }

    // Clear logs
    if (dom.clearLogBtn) {
        dom.clearLogBtn.addEventListener('click', () => {
            dom.logContainer.innerHTML = '';
            log("Console cleared.", "info");
        });
    }

    dom.codec.addEventListener('change', updateCodecOptions);
    dom.h264Level.addEventListener('change', () => {
        saveCurrentSettings();
        loadCodecInfo();
    });
    dom.outputTransform.addEventListener('change', () => {
        state.transformCustom = true;
        renderCodecInfo();
    });
    dom.codec.addEventListener('change', renderCodecInfo);

    let codecInfoCache = {};

    async function loadCodecInfo() {
        try {
            const level = dom.h264Level ? dom.h264Level.value : '';
            const url = '/api/codec_info' + (level ? `?level=${encodeURIComponent(level)}` : '');
            const res = await fetch(url, { cache: 'no-store' });
            codecInfoCache = await res.json();
            renderCodecInfo();
        } catch (e) {
            // Advisory readout; do not break page
        }
    }

    const PROFILE_LABELS = { high10: 'High 10', high: 'High' };

    function renderCodecInfo() {
        const info = codecInfoCache[dom.codec.value];
        dom.codecInfo.innerHTML = '';
        if (!info) return;

        const items = [
            { label: 'Encoder', value: info.encoder },
            { label: 'Profile', value: info.profile ? (PROFILE_LABELS[info.profile] || info.profile) : null },
            // The chip already reads "Level: ..."; prefixing the value too
            // rendered as "Level: Level 6.1".
            { label: 'Level', value: info.level || '', highlight: true },
            { label: 'Format', value: info.pix_fmt },
            { label: 'Transform', value: dom.outputTransform.value.replace('Output - ', '') }
        ].filter(item => Boolean(item.value));

        items.forEach(item => {
            const chip = document.createElement('span');
            chip.className = `spec-chip ${item.highlight ? 'spec-chip-highlight' : ''}`;
            chip.textContent = `${item.label}: ${item.value}`;
            dom.codecInfo.appendChild(chip);
        });
    }

    async function checkVersion() {
        try {
            const res = await fetch('/api/version', { cache: 'no-store' });
            const v = await res.json();
            dom.versionBanner.textContent = v.message || '';
            dom.versionBanner.classList.toggle('hidden', !v.stale);
            if (v.stale) {
                showToast("Build Updated", "A new code version is deployed on disk. Please restart or refresh.", "warning", 8000);
            }
        } catch (e) {
            // Offline or mid-restart
        }
    }

    dom.outputFilename.addEventListener('input', () => {
        state.filenameCustom = true;
    });
    dom.outputFilename.addEventListener('change', saveCurrentSettings);

    dom.reformatEnabled.addEventListener('change', () => {
        updateReformatUI();
        saveCurrentSettings();
    });
    [dom.reformatWidth, dom.reformatHeight].forEach(field => {
        field.addEventListener('input', updateReformatUI);
        field.addEventListener('change', saveCurrentSettings);
    });

    dom.sourceFps.addEventListener('input', () => {
        updateSequenceSummaryCard({
            start: state.frameRange.start,
            end: state.frameRange.end,
            width: state.sourceRes.width,
            height: state.sourceRes.height,
            pattern: dom.filenamePattern.value,
            range_string: dom.detectedRange.textContent
        });
    });

    // --- Run Conversion ---
    dom.runBtn.addEventListener('click', async () => {
        if (!dom.inputFolder.value || !dom.outputFolder.value) {
            showToast("Missing Folder", "Please select input and output sequence folders.", "error");
            return;
        }

        if (dom.reformatEnabled.checked) {
            const check = resolveDimensions(
                parseDimension(dom.reformatWidth),
                parseDimension(dom.reformatHeight),
                state.sourceRes.width,
                state.sourceRes.height
            );
            if (check.error) {
                showToast("Reformat Error", check.error, "error");
                return;
            }
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
            level: dom.h264Level.value,
            prores_profile: dom.codec.value.startsWith('prores') ? dom.codec.value.replace('prores_', '') : "2",
            prores_qscale: dom.proresQscale.value,
            output_transform: dom.outputTransform.value,
            audio_option: dom.audioOption.value,
            start_frame: state.frameRange.start,
            end_frame: state.frameRange.end,
            reformat_enabled: dom.reformatEnabled.checked,
            reformat_width: parseDimension(dom.reformatWidth),
            reformat_height: parseDimension(dom.reformatHeight)
        };

        if (dom.codec.value.startsWith('prores')) {
            if (config.prores_profile === '422') config.prores_profile = '2';
            if (config.prores_profile === '422_lt') config.prores_profile = '1';
            if (config.prores_profile === '444') config.prores_profile = '4';
        }

        setConvertingState(true);
        dom.logContainer.innerHTML = '';
        dom.progressBar.style.width = '0%';
        if (dom.progressPercentText) dom.progressPercentText.textContent = '0%';

        log("Starting conversion job...", "info");
        showToast("Job Started", `Converting to ${config.codec}...`, "info", 3000);
        await saveCurrentSettings();

        try {
            await API.startConversion(config);
        } catch (e) {
            log(`Failed to start job: ${e.message}`, 'error');
            showToast("Conversion Failed", e.message, "error");
            setConvertingState(false);
        }
    });

    dom.stopBtn.addEventListener('click', async () => {
        log('Stop requested by user...', 'info');
        showToast("Cancelling Job", "Sending cancellation signal...", "warning", 3000);
        await API.cancelConversion();
    });

    // Run init
    init();
});
