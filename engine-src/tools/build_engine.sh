#!/usr/bin/env bash
# Build the Real-ESRGAN-ncnn-vulkan engine with the SPANV2 model support.
# Requires: Visual Studio Build Tools (MSVC), Vulkan SDK at %VULKAN_SDK%
set -e

cd "$(dirname "$0")/../engine"

if [ -z "$VULKAN_SDK" ]; then
  echo "ERROR: VULKAN_SDK env var not set" >&2
  exit 1
fi
echo "VULKAN_SDK=$VULKAN_SDK"

# Locate MSVC via vswhere (Build Tools)
VSWHERE="/c/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe"
MSVC_BASE=$(ls -d "/c/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/"*/ 2>/dev/null | head -1)
if [ -z "$MSVC_BASE" ]; then
  echo "ERROR: MSVC not found" >&2
  exit 1
fi
echo "MSVC=$MSVC_BASE"

export CC="${MSVC_BASE}bin/Hostx64/x64/cl.exe"
export CXX="${MSVC_BASE}bin/Hostx64/x64/cl.exe"
export PATH="${MSVC_BASE}bin/Hostx64/x64:$PATH"

cmake -S src -B build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER="$CC" \
  -DCMAKE_CXX_COMPILER="$CXX" \
  -DVULKAN_SDK="$VULKAN_SDK" 2>&1 | tail -15

cmake --build build --config Release -j 8 2>&1 | tail -20
echo "=== built: $(ls -la build/Release/realesrgan-ncnn-vulkan.exe 2>/dev/null || find build -name '*.exe' | head -5) ==="
