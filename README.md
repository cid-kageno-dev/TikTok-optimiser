# TikTok Video Optimizer — Website

Open `index.html` in a modern browser. It runs without a backend and does not upload selected videos to a server.

Features:
- Multi-file metadata analysis (resolution, duration, file size, estimated average total bitrate)
- 4K pixel-dimension check
- Optional browser-side MP4 remux using FFmpeg.wasm loaded from jsDelivr
- Batch remux and download
- No paid API or PC required

Limitations:
- Frame rate is not reliably exposed by browser metadata, so this version does not claim to verify 60 fps.
- Remuxing copies streams; it does not upscale or create frames, improve source quality, or bypass TikTok transcoding.
- FFmpeg.wasm can use substantial memory; test with a small video first.
- The first remux requires internet to load FFmpeg from jsDelivr.
