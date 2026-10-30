# Third-Party Licenses: MPV, FFmpeg, and Bundled Libraries

This document provides license information for MPV, FFmpeg, and related media libraries bundled with the Linux AppImage distribution of Pirate Cinema 2.

## MPV Media Player
- **Package:** mpv
- **License:** GNU General Public License v2.0 or later (GPL-2.0-or-later) / LGPLv2.1+
- **Website:** [https://mpv.io](https://mpv.io)
- **Source Code:** [https://github.com/mpv-player/mpv](https://github.com/mpv-player/mpv)

## FFmpeg Libraries
- **Libraries:** libavcodec, libavformat, libavutil, libswscale, libswresample, libavfilter
- **License:** GNU Lesser General Public License v2.1 or later (LGPL-2.1+) / GPL-2.0+
- **Website:** [https://ffmpeg.org](https://ffmpeg.org)
- **Source Code:** [https://git.ffmpeg.org/ffmpeg.git](https://git.ffmpeg.org/ffmpeg.git)

## Subtitles, Scripting, and Rendering Libraries
- **libass** (Substation Alpha subtitle rendering): ISC License ([https://github.com/libass/libass](https://github.com/libass/libass))
- **Lua 5.2** (Scripting engine powering `cinema.lua`): MIT License ([https://www.lua.org](https://www.lua.org))
- **libplacebo** (GPU image and subtitle processing): LGPL-2.1+ ([https://code.videolan.org/videolan/libplacebo](https://code.videolan.org/videolan/libplacebo))
- **libuchardet** (Universal charset detection): Mozilla Public License 1.1 / GPL-2.0+ / LGPL-2.1+
- **libbluray** (Blu-ray navigation and demuxing): LGPL-2.1+
- **libvdpau** (Video Decode and Presentation API for Unix wrapper): MIT License

## Codecs and Formats
The bundled dynamic libraries may link to open-source decoders and encoders:
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
