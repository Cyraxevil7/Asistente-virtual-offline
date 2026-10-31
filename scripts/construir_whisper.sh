#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="${PROJECT_ROOT}/vendor"
SOURCE_DIR="${VENDOR_DIR}/whisper.cpp"
REPOSITORY_URL="https://github.com/ggml-org/whisper.cpp.git"
BUILD_DIR="${SOURCE_DIR}/build"
JOBS="${JOBS:-2}"

if ! command -v git >/dev/null || ! command -v cmake >/dev/null; then
    printf '%s\n' "Se requieren git y CMake para construir whisper-server." >&2
    exit 1
fi

if [[ ! -d "${SOURCE_DIR}" ]]; then
    mkdir -p "${VENDOR_DIR}"
    git clone --depth 1 "${REPOSITORY_URL}" "${SOURCE_DIR}"
elif [[ ! -f "${SOURCE_DIR}/CMakeLists.txt" ]]; then
    printf 'La carpeta %s existe, pero no parece contener whisper.cpp.\n' "${SOURCE_DIR}" >&2
    exit 1
fi

cmake -S "${SOURCE_DIR}" -B "${BUILD_DIR}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DWHISPER_BUILD_TESTS=OFF \
    -DWHISPER_BUILD_EXAMPLES=OFF \
    -DWHISPER_BUILD_SERVER=ON
cmake --build "${BUILD_DIR}" --config Release \
    --target whisper-server --parallel "${JOBS}"

printf 'whisper-server listo: %s\n' "${BUILD_DIR}/bin/whisper-server"
printf '%s\n' "Piper se instala como dependencia Python desde requirements.txt; no requiere un binario adicional en vendor/."
