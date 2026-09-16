# Shorts Studio user guide

This guide covers the v1.0.0 beta workflow.  The desktop bundle and the
container expose the same API and workspace.

## 1. Start a project

1. Open Shorts Studio and confirm the **Runtime diagnostics** card reports
   FFmpeg and the selected Whisper device as ready.
2. Drop a local video into the source panel or paste a YouTube URL.
3. Choose Local mode for CPU/GPU processing, or API mode when a MuAPI key is
   configured.  Select the number of clips, aspect ratio, language, and any
   caption/branding options.
4. Select **Generate shorts**.  Progress updates appear live while the
   transcript, highlights, and clips are produced.

![Workspace](screenshots/workspace.png)

The workspace screenshot covers source selection, Local/CPU fallback, render
progress, framing, captions, audio cleanup, and the export panel.

## 2. Review and edit

Open a completed project from the library.  The preview, transcript timeline,
captions, multi-cut ranges, and bounded undo/redo history are available in the
workspace.

![Dashboard](screenshots/dashboard.png)

The dashboard screenshot covers the project library, queue, retry/cancel
states, and opening a completed project.

Use the export presets for YouTube Shorts, TikTok, Instagram Reels, or a
square/feed deliverable.  The original source and completed clips remain in
the configured output folder.

## 3. Back up and restore

Use **Settings > Backup** to download a metadata backup.  Enable the optional
media switch only when the archive should carry generated clips; media backups
are bounded to 512 MB and never include provider credentials. Restore merges
new project IDs and automatically migrates older project formats.

For scripted deployments, inspect first and then apply migrations:

```powershell
python scripts/migrate_data.py --data-dir C:\path\to\shorts-data
python scripts/migrate_data.py --data-dir C:\path\to\shorts-data --apply
```

## 4. Publish and measure

Publishing is approval-first and private by default.  The **Publishing**
catalog shows whether YouTube, TikTok, or Instagram credentials are connected.
TikTok accepts a local rendered MP4 through its Content Posting API.  Instagram
Reels requires a public HTTPS `media_url`, because Meta fetches the video from
that URL.  Tokens stay in process memory and are never written to projects.

In the Export panel, choose TikTok or Instagram Reels, connect the account,
select a clip or variant, and approve a private upload. TikTok sends the local
rendered MP4 through the Content Posting API. Instagram requires a public
HTTPS `media_url` so Meta can fetch the video; a local path is never sent.

Create metadata variants for a clip with **Create variant from selected clip**.
Record views, likes, comments, and completion percentage in the analytics
controls. The feedback response compares retention and engagement and gives an
explainable next step; it never changes a project automatically.

## 5. Versioned API

New integrations should use `/api/v1/`.  The older `/api` paths remain as a
compatibility surface and return `Deprecation: true`, a `Sunset` date, and a
`Link` header pointing to the v1 equivalent.  OpenAPI is available at
`/docs` and `/openapi.json`; the error catalog is at `/api/v1/errors`.

![System diagnostics](screenshots/system-light.png)

The diagnostics screenshot covers FFmpeg/FFprobe, Whisper, CUDA/CPU fallback,
free space, and the refresh action.
