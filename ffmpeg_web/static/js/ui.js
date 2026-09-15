document.addEventListener('DOMContentLoaded', async () => {
    // --- State ---
    const state = {
        browsingPath: "",
        inputFolder: "",
        frameRange: { start: 0, end: 0 },
        sourceRes: { width: null, height: null },
        filenameCustom: false,
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
        logContainer: document.getElementById('log-container'),
        statusIndicator: document.getElementById('status-indicator'),
        depsWarning: document.getElementById('deps-warning'),

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

    // --- Reformat ---
    // Mirrors core/reformat.py so the preview always matches what the
    // backend will actually do. Rounding up (never down) means the output
    // is never smaller than what was asked for, and even dimensions are
    // mandatory for yuv420p chroma subsampling.
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

    // Mirrors default_output_transform_for_codec() on the backend, which
    // re-derives this when the client sends nothing, so the two cannot
    // drift into producing different pixels.
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
                log(`Dependencies not healthy: ${issues}`, 'error');
            } else if (dom.depsWarning) {
                dom.depsWarning.textContent = '';
                dom.depsWarning.classList.add('hidden');
                dom.runBtn.disabled = state.isConverting;
            }
        } catch (e) {
            log(`Failed to query dependency status: ${e.message}`, 'error');
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
                    } else {
                        // Clicking any frame picks the whole sequence it
                        // belongs to; the backend resolves the file to its
                        // folder and returns that sequence first.
                        handleFrameSelection(item.path);
                    }
                };
                if (!item.is_dir) {
                    li.title = "Select this sequence";
                }
                dom.fileList.appendChild(li);
            });
        } catch (e) {
            dom.fileList.innerHTML = `<li class="file-item log-error">Error: ${e.message}</li>`;
        }
    }

    // Parent directory of a POSIX path. The studio worktree has the same
    // helper; kept identical so the two front-ends stay comparable.
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
        // Pass the frame itself, not the folder: that is what tells the
        // backend which sequence was meant when a folder holds several.
        await scanForSequences(framePath);
        saveCurrentSettings();
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
                state.sourceRes = { width: null, height: null };
                updateReformatUI();
                return;
            }

            // Default to first found sequence
            const seq = sequences[0];
            dom.filenamePattern.value = seq.pattern;
            state.frameRange = { start: seq.start, end: seq.end };
            state.sourceRes = { width: seq.width || null, height: seq.height || null };
            dom.detectedRange.textContent = seq.range_string;
            if (seq.width && seq.height) {
                dom.detectedRange.textContent += ` \u2014 ${seq.width} \u00d7 ${seq.height}`;
            }
            updateReformatUI();

            // Auto-name the output after the sequence, but never overwrite a
            // name the user typed themselves -- having a custom delivery name
            // clobbered on every folder pick is exactly the retyping this is
            // meant to stop. Guard the extension match too: a filename with no
            // extension used to throw here and abort the scan.
            if (!state.filenameCustom) {
                const seqName = seq.head.replace(/[._]$/, "");
                const extMatch = dom.outputFilename.value.match(/\.\w+$/);
                dom.outputFilename.value = `${seqName}${extMatch ? extMatch[0] : ".mp4"}`;
            }

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
    // Once the user picks a transform we stop overriding it on codec change.
    dom.outputTransform.addEventListener('change', () => {
        state.transformCustom = true;
        renderCodecInfo();
    });
    dom.codec.addEventListener('change', renderCodecInfo);

    let codecInfoCache = {};

    async function loadCodecInfo() {
        try {
            const res = await fetch('/api/codec_info', { cache: 'no-store' });
            codecInfoCache = await res.json();
            renderCodecInfo();
        } catch (e) {
            // The readout is advisory; never let it break the page.
        }
    }

    const PROFILE_LABELS = { high10: 'High 10', high: 'High' };

    function renderCodecInfo() {
        const info = codecInfoCache[dom.codec.value];
        dom.codecInfo.textContent = '';
        if (!info) { return; }

        const levelText = info.level ? 'L ' + info.level : '';
        const parts = [info.encoder];
        if (info.profile) parts.push(PROFILE_LABELS[info.profile] || info.profile);
        if (levelText) parts.push(levelText);
        if (info.pix_fmt) parts.push(info.pix_fmt);
        parts.push(dom.outputTransform.value.replace('Output - ', ''));

        // Built as nodes rather than innerHTML so the level can be
        // emphasised without ever interpreting API text as markup.
        parts.forEach((text, i) => {
            if (i) dom.codecInfo.appendChild(document.createTextNode('  \u00b7  '));
            const span = document.createElement('span');
            span.textContent = text;
            if (levelText && text === levelText) {
                // The number people read off for delivery QC.
                span.style.fontWeight = '700';
                span.style.color = '#f18d79';
            }
            dom.codecInfo.appendChild(span);
        });
    }

    async function checkVersion() {
        try {
            const res = await fetch('/api/version', { cache: 'no-store' });
            const v = await res.json();
            dom.versionBanner.textContent = v.message || '';
            dom.versionBanner.classList.toggle('hidden', !v.stale);
        } catch (e) {
            // Offline or mid-restart; say nothing rather than cry wolf.
        }
    }

    // Typing in the filename marks it as the user's own, so folder
    // selection stops renaming it. Persisted, so it survives a restart.
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

    dom.runBtn.addEventListener('click', async () => {
        if (!dom.inputFolder.value || !dom.outputFolder.value) {
            alert("Please select input and output folders.");
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
                alert(`Reformat: ${check.error}`);
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
        log('Stop requested by user...', 'info');
        await API.cancelConversion();
    });

    // Run init
    init();
});
