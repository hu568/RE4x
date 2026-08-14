#!/usr/bin/env bash
# Build ncnn (Vulkan backend) as a static library with the MSYS2 ucrt64 MinGW toolchain.
# Source: E:/RE+SPANV2/engine/src/ncnn (Tencent/ncnn, submodule of the engine fork).
set -e
export MSYSTEM=UCRT64
export PATH=/ucrt64/bin:/c/Program\ Files/CMake/bin:/c/Users/Administrator/AppData/Local/Programs/Python/Python312:$PATH

cd /e/RE4x/tools

if [ ! -d ncnn-src/src ]; then
  echo "== copying ncnn source (excluding .git) =="
  rm -rf ncnn-src
  cp -r /e/RE+SPANV2/engine/src/ncnn ncnn-src
  rm -rf ncnn-src/.git ncnn-src/glslang/.git
fi

echo "== glslang submodule check =="
test -f ncnn-src/glslang/CMakeLists.txt || { echo "glslang submodule missing"; exit 1; }

echo "== cmake configure =="
cmake -S ncnn-src -B ncnn-build -G "MSYS Makefiles" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DNCNN_VULKAN=ON \
  -DNCNN_SYSTEM_GLSLANG=OFF \
  -DVulkan_INCLUDE_DIR=/ucrt64/include \
  -DVulkan_LIBRARY=/ucrt64/lib/libvulkan-1.dll.a \
  -DNCNN_BUILD_TOOLS=OFF \
  -DNCNN_BUILD_EXAMPLES=OFF \
  -DNCNN_BUILD_BENCHMARK=OFF \
  -DNCNN_BUILD_TESTS=OFF \
  -DNCNN_PYTHON=OFF \
  -DNCNN_SHARED_LIB=OFF \
  -DNCNN_OPENMP=OFF \
  2>&1 | tail -60

echo "== build =="
cmake --build ncnn-build -j 8 2>&1 | tail -30

echo "== artifacts =="
ls -la ncnn-build/src/libncnn.a
ls ncnn-build/glslang/*/lib*.a 2>/dev/null || find ncnn-build -name 'lib*.a' | head -20
