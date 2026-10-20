/**
 * client_web/static/app.js
 * 
 * Main client-side application controller coordinating URL resolution,
 * chunked stream downloading, Web Crypto decryption, and audio playback.
 */

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const urlInput = document.getElementById("urlInput");
    const resolveBtn = document.getElementById("resolveBtn");
    const formatBtns = document.querySelectorAll(".format-btn");
    const presetChips = document.querySelectorAll(".chip-btn");

    // Pipeline elements
    const pipelineContainer = document.getElementById("pipelineContainer");
    const step1 = document.getElementById("step1");
    const step2 = document.getElementById("step2");
    const step3 = document.getElementById("step3");
    const step4 = document.getElementById("step4");
    const progressBar = document.getElementById("progressBar");
    const progressLabel = document.getElementById("progressLabel");
    const progressSpeed = document.getElementById("progressSpeed");

    // Player elements
    const playerCard = document.getElementById("playerCard");
    const coverImg = document.getElementById("coverImg");
    const trackTitle = document.getElementById("trackTitle");
    const trackArtist = document.getElementById("trackArtist");
    const trackAlbum = document.getElementById("trackAlbum");
    const badgeCodec = document.getElementById("badgeCodec");
    const badgeDrm = document.getElementById("badgeDrm");
    const audioElement = document.getElementById("audioElement");
    const playPauseBtn = document.getElementById("playPauseBtn");
    const playIcon = document.getElementById("playIcon");
    const pauseIcon = document.getElementById("pauseIcon");
    const seekSlider = document.getElementById("seekSlider");
    const currentTimeText = document.getElementById("currentTimeText");
    const durationTimeText = document.getElementById("durationTimeText");
    const volumeSlider = document.getElementById("volumeSlider");
    const downloadBtn = document.getElementById("downloadBtn");
    const visualizerCanvas = document.getElementById("visualizerCanvas");

    // Inspector elements
    const inspectorTrackId = document.getElementById("inspectorTrackId");
    const inspectorKid = document.getElementById("inspectorKid");
    const inspectorKey = document.getElementById("inspectorKey");
    const inspectorTime = document.getElementById("inspectorTime");
    const inspectorSpeed = document.getElementById("inspectorSpeed");

    // State
    let selectedFormat = "aac";
    let currentTrack = null;
    let decryptedBlobUrl = null;
    let decryptedBlob = null;
    let decryptor = new ClientAudioDecryptor();
    let visualizer = new AudioSpectrumVisualizer(visualizerCanvas, audioElement);

    // Format selection
    formatBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            formatBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            selectedFormat = btn.dataset.format;
        });
    });

    // Preset chips
    presetChips.forEach(chip => {
        chip.addEventListener("click", () => {
            urlInput.value = chip.dataset.url;
            startPipeline();
        });
    });

    // Submit handler
    resolveBtn.addEventListener("click", () => {
        startPipeline();
    });

    urlInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            startPipeline();
        }
    });

    // Format seconds to mm:ss
    function formatTime(seconds) {
        if (isNaN(seconds) || seconds < 0) return "0:00";
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, "0")}`;
    }

    // Set step state
    function setStepState(stepElem, state) {
        stepElem.classList.remove("active", "done");
        if (state) stepElem.classList.add(state);
    }

    // Main pipeline execution
    async function startPipeline() {
        const url = urlInput.value.trim();
        if (!url) {
            alert("Please paste an Apple Music link.");
            return;
        }

        // Reset UI
        resolveBtn.disabled = true;
        pipelineContainer.classList.add("active");
        playerCard.classList.remove("active");
        progressBar.style.width = "0%";
        progressLabel.textContent = "Connecting to license broker...";
        progressSpeed.textContent = "";

        setStepState(step1, "active");
        setStepState(step2, null);
        setStepState(step3, null);
        setStepState(step4, null);

        try {
            // STEP 1: Resolve metadata & stream manifest
            progressLabel.textContent = "Resolving track metadata & CDN streams...";
            progressBar.style.width = "15%";

            const resolveResponse = await fetch("/api/resolve", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url, format: selectedFormat })
            });

            const resolveData = await resolveResponse.json();
            if (!resolveData.success || !resolveData.track) {
                throw new Error(resolveData.error || "Failed to resolve track.");
            }

            currentTrack = resolveData.track;
            setStepState(step1, "done");

            // STEP 2: Key Resolution
            setStepState(step2, "active");
            progressLabel.textContent = `Acquired key for KID: ${currentTrack.kid || "CENC"}...`;
            progressBar.style.width = "30%";

            if (!currentTrack.key && !currentTrack.drm_free) {
                throw new Error("Track is encrypted and no decryption key could be obtained.");
            }

            setStepState(step2, "done");

            // STEP 3: Client Stream Fetching
            setStepState(step3, "active");
            progressLabel.textContent = "Downloading encrypted audio chunks from Apple CDN...";

            // Use the proxy endpoint to guarantee no browser CORS issues
            const streamUrl = currentTrack.proxy_stream_url || currentTrack.stream_url;
            const startTime = performance.now();

            const streamResponse = await fetch(streamUrl);
            if (!streamResponse.ok) {
                throw new Error(`Stream download failed with status ${streamResponse.status}`);
            }

            const contentLength = +streamResponse.headers.get("Content-Length") || 0;
            const reader = streamResponse.body.getReader();
            const chunks = [];
            let receivedBytes = 0;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                chunks.push(value);
                receivedBytes += value.length;

                if (contentLength > 0) {
                    const pct = 30 + Math.round((receivedBytes / contentLength) * 45); // 30% to 75%
                    progressBar.style.width = `${pct}%`;
                    const elapsedSec = (performance.now() - startTime) / 1000;
                    const speedKBps = (receivedBytes / 1024 / elapsedSec).toFixed(1);
                    progressLabel.textContent = `Downloading stream: ${(receivedBytes / (1024 * 1024)).toFixed(2)} MB of ${(contentLength / (1024 * 1024)).toFixed(2)} MB`;
                    progressSpeed.textContent = `${speedKBps} KB/s`;
                }
            }

            // Concatenate chunks into a single ArrayBuffer
            const fullBuffer = new Uint8Array(receivedBytes);
            let chunkOffset = 0;
            for (const chunk of chunks) {
                fullBuffer.set(chunk, chunkOffset);
                chunkOffset += chunk.length;
            }

            setStepState(step3, "done");

            // STEP 4: Client-Side Decryption via Web Crypto API
            setStepState(step4, "active");
            progressLabel.textContent = "Decrypting audio samples in browser via Web Crypto API (AES-128-CTR)...";
            progressSpeed.textContent = "Local Hardware Acceleration";

            let finalAudioBuffer = fullBuffer.buffer;
            let decryptionMetrics = { durationMs: 0, speedMbps: 0 };

            if (!currentTrack.drm_free && currentTrack.key) {
                const decryptResult = await decryptor.decrypt(
                    fullBuffer.buffer,
                    currentTrack.key,
                    currentTrack.kid,
                    (percent) => {
                        progressBar.style.width = `${75 + Math.round(percent * 0.25)}%`;
                    }
                );
                finalAudioBuffer = decryptResult.decryptedBuffer;
                decryptionMetrics = decryptResult.metrics;
            }

            progressBar.style.width = "100%";
            setStepState(step4, "done");
            progressLabel.textContent = "Track decrypted and ready for instant playback!";
            progressSpeed.textContent = `Decrypted in ${decryptionMetrics.durationMs}ms`;

            // STEP 5: Mount Track into Player
            mountPlayer(finalAudioBuffer, decryptionMetrics);

        } catch (err) {
            console.error("Pipeline error:", err);
            progressLabel.textContent = `Error: ${err.message}`;
            progressSpeed.textContent = "Failed";
            progressBar.style.background = "var(--accent-rose)";
        } finally {
            resolveBtn.disabled = false;
        }
    }

    // Mount decrypted audio into player
    function mountPlayer(audioArrayBuffer, metrics) {
        if (decryptedBlobUrl) {
            URL.revokeObjectURL(decryptedBlobUrl);
        }

        decryptedBlob = new Blob([audioArrayBuffer], { type: "audio/mp4" });
        decryptedBlobUrl = URL.createObjectURL(decryptedBlob);

        coverImg.src = currentTrack.cover_url || "/static/logo.svg";
        trackTitle.textContent = currentTrack.title || "Unknown Title";
        trackArtist.textContent = currentTrack.artist || "Unknown Artist";
        trackAlbum.textContent = currentTrack.album || "Unknown Album";
        badgeCodec.textContent = (currentTrack.codec || "AAC-LC").toUpperCase();
        badgeDrm.textContent = currentTrack.drm_free ? "DRM-FREE" : "CLIENT DECRYPTED";

        // Technical Inspector
        inspectorTrackId.textContent = currentTrack.id || "-";
        inspectorKid.textContent = currentTrack.kid || "N/A";
        inspectorKey.textContent = currentTrack.key || "N/A";
        inspectorTime.textContent = `${metrics.durationMs} ms`;
        inspectorSpeed.textContent = `${metrics.speedMbps} Mbps`;

        // Setup audio element
        audioElement.src = decryptedBlobUrl;
        audioElement.load();

        playerCard.classList.add("active");
        playerCard.scrollIntoView({ behavior: "smooth" });
    }

    // Audio Player Controls
    playPauseBtn.addEventListener("click", () => {
        if (audioElement.paused) {
            audioElement.play();
            visualizer.start();
            playIcon.style.display = "none";
            pauseIcon.style.display = "block";
        } else {
            audioElement.pause();
            visualizer.stop();
            playIcon.style.display = "block";
            pauseIcon.style.display = "none";
        }
    });

    audioElement.addEventListener("timeupdate", () => {
        const cur = audioElement.currentTime;
        const dur = audioElement.duration || 0;
        currentTimeText.textContent = formatTime(cur);
        durationTimeText.textContent = formatTime(dur);
        if (dur > 0) {
            seekSlider.value = (cur / dur) * 100;
        }
    });

    seekSlider.addEventListener("input", () => {
        const dur = audioElement.duration || 0;
        if (dur > 0) {
            audioElement.currentTime = (seekSlider.value / 100) * dur;
        }
    });

    volumeSlider.addEventListener("input", () => {
        audioElement.volume = volumeSlider.value;
    });

    audioElement.addEventListener("ended", () => {
        playIcon.style.display = "block";
        pauseIcon.style.display = "none";
        visualizer.stop();
    });

    // Save/Download decrypted .m4a file locally
    downloadBtn.addEventListener("click", () => {
        if (!decryptedBlob) return;
        const filename = `${currentTrack.artist || "Artist"} - ${currentTrack.title || "Track"}.m4a`
            .replace(/[\\/:*?"<>|]/g, "_");

        const a = document.createElement("a");
        a.href = decryptedBlobUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    });
});
