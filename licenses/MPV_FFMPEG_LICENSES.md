# Third-Party Licenses: MPV, FFmpeg, and Bundled Libraries

This document records currently known build settings for MPV, FFmpeg, and their media libraries in the Linux AppImage and Flatpak recipes. It is not a substitute for the license texts and source corresponding to each built binary.

## MPV Media Player
- **Package:** mpv
- **License:** mpv is generally offered under GPL-2.0-or-later; exact build features and linked libraries must be checked against the pinned revision.
- **Website:** [https://mpv.io](https://mpv.io)
- **Source Code:** [https://github.com/mpv-player/mpv](https://github.com/mpv-player/mpv)

## FFmpeg Libraries
- **Libraries:** libavcodec, libavformat, libavutil, libswscale, libswresample, libavfilter
- **License:** FFmpeg is LGPL-2.1-or-later by default; this project's Linux recipe passes `--enable-gpl` and `--enable-libx264`, so the resulting build is GPL-enabled. Do not describe these binaries as LGPL-only.
- **Website:** [https://ffmpeg.org](https://ffmpeg.org)
- **Source Code:** [https://git.ffmpeg.org/ffmpeg.git](https://git.ffmpeg.org/ffmpeg.git)

The Flatpak recipe pins FFmpeg 8.1.2 and x264 commit `b35605ace3ddf7c1a5d67a2eb553f034aef41d55`; the MPV recipe pins v0.41.0. AppImage uses the Linux media bundler and pinned source configuration in `scripts/bundle_linux_ffmpeg.py` and `scripts/bundle_linux_mpv.py`. Preserve those source archives, patches, configuration and compiler inputs with each release. A source link alone is not the corresponding source offer required for a binary distribution.

## Subtitles, Scripting, and Rendering Libraries
- **libass** (Substation Alpha subtitle rendering): ISC License ([https://github.com/libass/libass](https://github.com/libass/libass))
- **Lua 5.2** (Scripting engine powering `cinema.lua`): MIT License ([https://www.lua.org](https://www.lua.org))
- **libplacebo** (GPU image and subtitle processing): LGPL-2.1+ ([https://code.videolan.org/videolan/libplacebo](https://code.videolan.org/videolan/libplacebo))
- **libuchardet** (Universal charset detection): Mozilla Public License 1.1 / GPL-2.0+ / LGPL-2.1+
- **libbluray** (Blu-ray navigation and demuxing): LGPL-2.1+
- **libvdpau** (Video Decode and Presentation API for Unix wrapper): MIT License

## Codecs and Formats
The exact dynamic libraries vary with the platform package. The Linux FFmpeg build explicitly enables x264, dav1d, Opus, VPx, VAAPI and NVENC; resolve the final linked-library set from the built binaries rather than treating this list as exhaustive:
- **libdav1d** (AV1 decoder): BSD-2-Clause
- **libvpx** (VP8/VP9 video codec): BSD-3-Clause
- **libx264** / **libx265** (H.264 / HEVC video encoders/decoders): GPL-2.0+
- **libopus** (Opus audio codec): BSD-3-Clause
- **libvorbis** / **libogg** (Ogg Vorbis audio codecs): BSD-3-Clause
- **libtheora** (Theora video codec): BSD-3-Clause
- **libflac** (FLAC audio codec): BSD-3-Clause / GPL

## System and Hardware Integration Libraries (Host Provided)
To maintain hardware acceleration, driver compatibility, display protocol support, and audio integration, the following libraries are intentionally **not** bundled and are loaded from the user's host Linux system:
- **C/C++ Runtimes & Kernels:** `libc.so.6`, `libm.so.6`, `libpthread.so.0`, `libdl.so.2`, `librt.so.1`, `ld-linux-x86-64.so.2`
- **Graphics & Hardware Acceleration:** `libGL.so*`, `libEGL.so*`, `libdrm.so*`, `libvulkan.so*`, `libgbm.so*`, `libva.so*`, `libva-drm.so*`, `libva-x11.so*`
- **Display Protocols:** `libX11.so*`, `libXext.so*`, `libXrandr.so*`, `libXrender.so*`, `libxcb*.so*`, `libwayland-client.so*`, `libwayland-cursor.so*`, `libwayland-egl.so*`
- **Audio Output Servers:** `libasound.so*` (ALSA), `libpulse.so*` (PulseAudio), `libpipewire-*.so*` (PipeWire), `libjack.so*` (JACK)
