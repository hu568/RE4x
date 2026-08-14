#!/usr/bin/env bash
# Build the custom ffmpeg.exe with the in-process realesrgan (ncnn-Vulkan) filter.
#
# Usage (MSYS2 bash, from anywhere):
#   bash ffmpeg-realesrgan/build_filter.sh
#
# Prerequisites (already documented in tools/ffmpeg-features.md, plus):
#   - MSYS2 ucrt64 toolchain, x264, nasm, pkgconf, vulkan-loader, vulkan-headers, glslang
#   - tools/ncnn-src  (Tencent/ncnn, with the glslang submodule)
#   - tools/ncnn-build (static libncnn.a produced by tools/build_ncnn.sh)
#   - tools/ffmpeg-src (ffmpeg n9.0 source tree)
#
# The filter sources live in ffmpeg-realesrgan/ (tracked by git) and are copied
# into tools/ffmpeg-src/libavfilter/ before configure. Patches are idempotent.
#
# Output: tools/ffmpeg.exe (previous binary backed up to tools/ffmpeg.exe.bak)
set -e
export MSYSTEM=UCRT64
export PATH=/ucrt64/bin:/c/Program\ Files/CMake/bin:$PATH

REPO=/e/RE4x
FILTER_SRC=$REPO/ffmpeg-realesrgan
FFSRC=$REPO/tools/ffmpeg-src
NCNN_SRC=$REPO/tools/ncnn-src
NCNN_BUILD=$REPO/tools/ncnn-build

if [ ! -f "$NCNN_BUILD/src/libncnn.a" ]; then
    echo "ERROR: $NCNN_BUILD/src/libncnn.a not found — run tools/build_ncnn.sh first" >&2
    exit 1
fi
if [ ! -d "$FFSRC/libavfilter" ]; then
    echo "ERROR: ffmpeg source tree not found at $FFSRC" >&2
    exit 1
fi

cd "$FFSRC"

# ── 1. Copy filter sources into libavfilter ───────────────────────────────
cp -f "$FILTER_SRC"/vf_realesrgan.c \
       "$FILTER_SRC"/realesrgan_capi.cpp \
       "$FILTER_SRC"/realesrgan_capi.h \
       "$FILTER_SRC"/realesrgan.cpp \
       "$FILTER_SRC"/realesrgan.h \
       "$FILTER_SRC"/*.spv.hex.h \
       libavfilter/

# ── 2. Register the filter (idempotent) ────────────────────────────────────
if ! grep -q 'ff_vf_realesrgan' libavfilter/allfilters.c; then
    sed -i '/extern const FFFilter ff_vf_realtime;/a extern const FFFilter ff_vf_realesrgan;' libavfilter/allfilters.c
fi
if ! grep -q 'CONFIG_REALESRGAN_FILTER' libavfilter/Makefile; then
    sed -i '/^OBJS-\$(CONFIG_DNN_PROCESSING_FILTER)/a OBJS-$(CONFIG_REALESRGAN_FILTER)           += vf_realesrgan.o realesrgan_capi.o realesrgan.o' libavfilter/Makefile
fi
if ! grep -q '^realesrgan_filter_deps=' configure; then
    sed -i '/^scale_filter_deps="swscale"$/a realesrgan_filter_deps="swscale"' configure
fi

# ── 3. Configure (whitelist build + realesrgan filter + static ncnn) ──────
if [ -f config.mak ]; then
    make distclean >/dev/null 2>&1 || true
fi
GLSLANG_LIB_DIRS=""
for d in \
    "$NCNN_BUILD/glslang/glslang" \
    "$NCNN_BUILD/glslang/glslang/OSDependent/Windows" \
    "$NCNN_BUILD/glslang/OGLCompilersDLL" \
    "$NCNN_BUILD/glslang/SPIRV" \
    "$NCNN_BUILD/glslang/glslang/MachineIndependent" \
    "$NCNN_BUILD/glslang/glslang/GenericCodeGen"; do
    if [ -d "$d" ] && ls "$d"/lib*.a >/dev/null 2>&1; then
        GLSLANG_LIB_DIRS="$GLSLANG_LIB_DIRS -L$d"
    fi
done
# fallback: find any glslang static lib dirs
if [ -z "$GLSLANG_LIB_DIRS" ]; then
    GLSLANG_LIB_DIRS=$(find "$NCNN_BUILD" -name 'libglslang.a' -printf ' -L%h')
fi

./configure --prefix=/usr/local \
  --disable-everything --disable-network --disable-autodetect \
  --disable-doc --disable-debug --disable-ffplay --disable-ffprobe \
  --enable-ffmpeg --enable-static --disable-shared --enable-small \
  --enable-gpl --enable-libx264 --enable-zlib --enable-swscale \
  --pkg-config-flags=--static --extra-ldflags=-static-libgcc\ -static-libstdc++ \
  --enable-protocol=file,pipe \
  --enable-demuxer=image2,mov,matroska,avi \
  --enable-muxer=image2,mp4,mov,gif \
  --enable-decoder=mjpeg,png,bmp,webp,tiff,h264,hevc,mpeg4,vp8,vp9 \
  --enable-encoder=libx264,mjpeg,png,gif \
  --enable-filter=scale,crop,blend,pad,split,fps,palettegen,paletteuse,realesrgan \
  --enable-parser=h264,hevc,mpeg4,vp8,vp9,aac,mp3 \
  --extra-cflags="-I$NCNN_SRC/src -I$NCNN_BUILD/src" \
  --extra-cxxflags="-I$NCNN_SRC/src -I$NCNN_BUILD/src -I$FILTER_SRC" \
  --extra-ldflags="-L$NCNN_BUILD/src$GLSLANG_LIB_DIRS" \
  --extra-libs="-lncnn -lglslang -lMachineIndependent -lGenericCodeGen -lOSDependent -lOGLCompiler -lSPIRV -lvulkan-1 -lstdc++ -lwinpthread"

# ── 3b. Pin x264/zlib/winpthread to their static archives ────────────────
# Without the global -static flag, ld prefers the import libs (.dll.a) for
# these, producing a runtime dependency on libx264-165.dll/zlib1.dll/
# libwinpthread-1.dll. Rewrite config.mak to link the .a files directly
# (vulkan-1 stays dynamic on purpose: it is a Windows system library).
sed -i 's|-lx264|/ucrt64/lib/libx264.a|g; s|-lz |/ucrt64/lib/libz.a |g; s|-lz$|/ucrt64/lib/libz.a|g; s|-lwinpthread|/ucrt64/lib/libwinpthread.a|g' ffbuild/config.mak

# ── 4. Build ───────────────────────────────────────────────────────────────
# NOTE: `make ffmpeg` does NOT work — MSYS make matches the bare name against
# the stale ffmpeg.exe file (no deps) and reports nothing to do. Build the
# real target: all → ffmpeg.exe (from ffmpeg_g.exe via the $(PROGS) rule).
make -j"$(nproc)" all

# ── 5. Install ─────────────────────────────────────────────────────────────
cd "$REPO"
if [ -f tools/ffmpeg.exe ]; then
    cp -f tools/ffmpeg.exe tools/ffmpeg.exe.bak
fi
cp -f "$FFSRC/ffmpeg.exe" tools/ffmpeg.exe
echo "=== built: tools/ffmpeg.exe ($(stat -c%s tools/ffmpeg.exe) bytes) ==="
