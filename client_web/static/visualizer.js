/**
 * client_web/static/visualizer.js
 * 
 * Real-time Web Audio API frequency visualizer with glowing gradient spectrum.
 */

class AudioSpectrumVisualizer {
    constructor(canvasElement, audioElement) {
        this.canvas = canvasElement;
        this.ctx = canvasElement.getContext("2d");
        this.audio = audioElement;
        this.audioCtx = null;
        this.analyser = null;
        this.source = null;
        this.animationId = null;
        this.dataArray = null;
        this.bufferLength = 0;
        this.initResizeListener();
    }

    initResizeListener() {
        const resize = () => {
            const rect = this.canvas.getBoundingClientRect();
            this.canvas.width = rect.width * (window.devicePixelRatio || 1);
            this.canvas.height = rect.height * (window.devicePixelRatio || 1);
        };
        window.addEventListener("resize", resize);
        resize();
    }

    setupAudioContext() {
        if (this.audioCtx) return;
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        this.audioCtx = new AudioContext();
        this.analyser = this.audioCtx.createAnalyser();
        this.analyser.fftSize = 128;
        this.analyser.smoothingTimeConstant = 0.82;

        this.source = this.audioCtx.createMediaElementSource(this.audio);
        this.source.connect(this.analyser);
        this.analyser.connect(this.audioCtx.destination);

        this.bufferLength = this.analyser.frequencyBinCount;
        this.dataArray = new Uint8Array(this.bufferLength);
    }

    start() {
        this.setupAudioContext();
        if (this.audioCtx.state === "suspended") {
            this.audioCtx.resume();
        }

        if (this.animationId) cancelAnimationFrame(this.animationId);

        const render = () => {
            this.animationId = requestAnimationFrame(render);
            this.analyser.getByteFrequencyData(this.dataArray);

            const w = this.canvas.width;
            const h = this.canvas.height;
            this.ctx.clearRect(0, 0, w, h);

            const barCount = 36;
            const spacing = 4 * (window.devicePixelRatio || 1);
            const totalSpacing = spacing * (barCount - 1);
            const barWidth = (w - totalSpacing) / barCount;

            // Draw glowing gradient frequency bars
            const gradient = this.ctx.createLinearGradient(0, h, 0, 0);
            gradient.addColorStop(0, "rgba(99, 102, 241, 0.4)");   // Indigo
            gradient.addColorStop(0.5, "rgba(168, 85, 247, 0.8)"); // Violet
            gradient.addColorStop(1, "rgba(6, 182, 212, 1.0)");   // Cyan bloom

            this.ctx.fillStyle = gradient;
            this.ctx.shadowBlur = 12;
            this.ctx.shadowColor = "rgba(168, 85, 247, 0.6)";

            for (let i = 0; i < barCount; i++) {
                const dataIndex = Math.floor((i / barCount) * (this.bufferLength * 0.75));
                const val = this.dataArray[dataIndex] || 0;
                const percent = val / 255;
                const barHeight = Math.max(4, percent * h * 0.9);
                const x = i * (barWidth + spacing);
                const y = h - barHeight;

                this.ctx.beginPath();
                this.ctx.roundRect(x, y, barWidth, barHeight, 3);
                this.ctx.fill();
            }
        };

        render();
    }

    stop() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        if (this.ctx) {
            this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        }
    }
}

window.AudioSpectrumVisualizer = AudioSpectrumVisualizer;
