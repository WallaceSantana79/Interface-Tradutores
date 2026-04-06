#!/usr/bin/env bash
set -euo pipefail

CLEAN=0
if [[ "${1:-}" == "-c" || "${1:-}" == "--clean" ]]; then
  CLEAN=1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-build"

cd "${PROJECT_ROOT}"

PYTHON_BIN="python"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    echo "Python nao encontrado no PATH (python/python3)."
    exit 1
  fi
fi

if [[ "${CLEAN}" -eq 1 ]]; then
  echo "Limpando artefatos antigos (build/dist) ..."
  rm -rf "${PROJECT_ROOT}/build" "${PROJECT_ROOT}/dist"
fi

echo "Instalando dependencias de build ..."
if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Criando ambiente virtual de build em ${VENV_DIR} ..."
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

python -m pip install --upgrade pip

echo "Instalando requirements-build.txt ..."
python -m pip install -r "${PROJECT_ROOT}/requirements-build.txt"

echo "Gerando executavel onedir com PyInstaller ..."
python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name InterfaceTradutores \
  --collect-all tkinterdnd2 \
  --collect-all UnityPy \
  --distpath "${PROJECT_ROOT}/dist" \
  --workpath "${PROJECT_ROOT}/build" \
  "${PROJECT_ROOT}/app.py"

BIN_PATH="${PROJECT_ROOT}/dist/InterfaceTradutores/InterfaceTradutores"
if [[ ! -f "${BIN_PATH}" ]]; then
  echo "Build executado, mas o executavel nao foi encontrado em: ${BIN_PATH}"
  exit 1
fi

echo ""
echo "Build finalizado com sucesso."
echo "Executavel: ${BIN_PATH}"
