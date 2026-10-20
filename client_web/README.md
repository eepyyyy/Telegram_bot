# am-client: Client-Side Audio Decryption Web App

A standalone web application demonstrating **zero-server-storage client-side decryption** for Apple Music audio streams.

---

## 🌟 Key Architecture & Highlights

```
[Apple CDN (Akamai)] ────────(Encrypted Audio Chunks)───────> [User's Web Browser]
                                                                      │
[client_web Server] ───(JSON: Metadata + 16-byte Key)───────>        │ (Web Crypto API AES-128-CTR)
                                                                      │
                                                                      v
                                                            [HTML5 Audio Player]
                                                            [Export Decrypted .m4a]
```

1. **Zero Media Storage on Server**: The server only acts as a lightweight metadata and key exchange broker (~2 KB JSON). It never downloads, processes, or stores large audio files.
2. **Direct High-Speed Streaming**: Audio is fetched directly from Apple CDN chunk-by-chunk in the browser via `ReadableStream`.
3. **Hardware-Accelerated Web Crypto API**: Audio decryption is performed 100% locally on the client machine using native browser cryptography (`window.crypto.subtle.decrypt` with AES-CTR).
4. **Instant In-Memory Playback & Export**: Decrypted audio is instantly playable with real-time waveform visualization and downloadable directly as a clean `.m4a` file.

---

## 🚀 Running the App

### 1. Locally (Development)
Using the repository virtual environment:
```powershell
.\.venv\Scripts\python.exe client_web/run.py
```
Or with `uv`:
```bash
uv run python client_web/run.py
```
Access the application at: **`http://localhost:8090`**

### 2. Custom Port
```bash
uv run python client_web/run.py --port 8095
```

---

## 📁 File Structure

```
client_web/
├── server.py              # Async aiohttp server (Metadata & Key broker + CORS streaming proxy)
├── run.py                 # CLI launcher script
├── static/
│   ├── index.html         # Premium dark-mode Single Page Application
│   ├── style.css          # Glassmorphism design system & micro-animations
│   ├── app.js             # Pipeline orchestrator & audio player UI
│   ├── decryptor.js       # Web Crypto API ISO-BMFF / MP4 CENC AES-128 decryptor
│   └── visualizer.js      # Real-time Web Audio API frequency spectrum canvas
└── README.md
```
