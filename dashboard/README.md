# ⚡ Telegram Bot Control Plane & Telemetry Dashboard

A modern, high-performance web dashboard with an authentic **Monkeytype** aesthetic designed for managing and monitoring your Apple Music Telegram Bot in real-time.

---

## ✨ Features

- **⚡ Instant Bot Controls**:
  - **Emergency Pause / Resume**: Pause all download queues immediately with one click or via keyboard `<kbd>Tab</kbd> + <kbd>Enter</kbd>`.
  - **Maintenance Mode**: Toggle maintenance mode with customizable notification messages for bot users.
  - **Task Termination**: View all running `gamdl` / `yt-dlp` download subprocesses and kill/cancel any stuck task immediately.
  - **Queue Purging**: Selectively purge ALAC, Lossless, AAC, Dolby Atmos, or Music Video queues.
- **📊 Real-time Telemetry & Metrics**:
  - **Active Downloads Monitor**: Live progress bars, song title, artist, user ID, requested format, and elapsed timer.
  - **Queue Inspector**: Interactive tabs showing pending job depths across all formats.
  - **Host & System Gauges**: CPU utilization %, RAM memory %, and storage disk space.
  - **Database Catalog Explorer**: Total tracks, albums, VIP users, downloads today, and format distribution.
  - **User Manager**: Search users, view activity, and grant/revoke VIP premium tier with custom daily limits.
- **💻 Live Terminal Log Streamer**:
  - Auto-scrolling, searchable console log viewer with log level filtering (`ALL`, `INFO`, `WARNING`, `ERROR`).
- **🎨 Monkeytype Theme System**:
  - Serika Dark (Default), Carbon, Dracula, Matrix, and 8008 themes.
  - `Ctrl+K` interactive Command Palette for lightning-fast keyboard navigation.
- **🔐 Secure Authentication**:
  - Password protected with HMAC-SHA256 session tokens.

---

## 🚀 Hosting & Deployment Options

### Option 1: Built-in Zero-Config Serving (Recommended)
The dashboard is automatically built into `dashboard/dist` and served directly by your bot's web server at:
- **Local**: `http://localhost:8080/dashboard`
- **Domain**: `https://tbot.eepy.in/dashboard`

No extra server or configuration needed!

---

### Option 2: Deploy on Cloudflare Pages (Free & Global CDN)

You can host this dashboard on Cloudflare Pages so it is accessible globally with zero latency.

#### Method A: Direct Upload via Cloudflare Dashboard
1. Run `npm run build` inside the `dashboard/` directory.
2. In your [Cloudflare Dashboard](https://dash.cloudflare.com), go to **Workers & Pages** > **Create application** > **Pages** > **Upload assets**.
3. Upload the `dashboard/dist` folder.
4. Set your Project Name (e.g. `tbot-control`).
5. Once deployed, open your `https://tbot-control.pages.dev` URL, enter your **Admin Password**, and set the **Backend Server URL** (e.g. `https://tbot.eepy.in`).

#### Method B: Cloudflare Pages Git Integration
- **Framework preset**: `Vite`
- **Build command**: `npm run build`
- **Build output directory**: `dist`
- **Root directory**: `dashboard`

---

## 🔑 Configuration (`.env`)

Add the following variables to your root `.env` file:

```env
# Admin Dashboard Authentication Password
ADMIN_PASSWORD=your_secure_admin_password_here

# Optional: Custom JWT Token Secret (auto-generated if omitted)
JWT_SECRET=super_secret_jwt_key_here
```

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| <kbd>Ctrl</kbd> + <kbd>K</kbd> / <kbd>Cmd</kbd> + <kbd>K</kbd> | Open Monkeytype Command Palette |
| <kbd>Shift</kbd> + <kbd>Enter</kbd> | Toggle Emergency Pause / Resume |
| <kbd>Esc</kbd> | Close any open modal or dialog |
