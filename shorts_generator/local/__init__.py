"""Local-mode backends — no MuAPI calls, runs on your machine.

Used when the pipeline is invoked with mode="local". Requires the optional
deps in requirements-local.txt (yt-dlp, faster-whisper, openai, google-genai,
opencv, and the bundled FFmpeg runtime) plus an LLM API key for highlight
ranking. Rendering is implemented directly with FFmpeg and OpenCV.
"""
