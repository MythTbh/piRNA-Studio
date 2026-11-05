#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
source packaging/runtime.sh
if [ -n "$runner" ] && "$runner" packaging/check_runtime.py; then exit 0; fi
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) platform=osx-arm64; digest=acef4eaab19ec2174ad5a449e5aad981ca326270db819502ff096a92fc31caa6 ;;
  Darwin-x86_64) platform=osx-64; digest=17b20c4271d65c030a5c86788f5ca86eb575187209f626edabdb8c6a875c6838 ;;
  Linux-x86_64) platform=linux-64; digest=9a97976244929bbae28fb1fae504e74a3e7e6d1932870e3a03321f01b7fbd07b ;;
  *) printf '%s\n' 'Automatic setup supports macOS Apple Silicon/Intel and Linux x86_64. Other platforms can use the Docker package.' >&2; exit 1 ;;
esac
mkdir -p .runtime
if ! mkdir .runtime/setup.lock 2>/dev/null; then
  printf '%s\n' 'Setup is already running. If it was interrupted, close other setup windows and remove .runtime/setup.lock before retrying.' >&2
  exit 1
fi
trap 'rmdir .runtime/setup.lock 2>/dev/null || true' EXIT
trap 'exit 130' INT TERM
install_runtime() {
printf '%s\n' 'Preparing piRNA Studio research tools. The first launch needs internet and several minutes.' 'Dependencies stay inside this app folder. No administrator password is required.'
archive="$PWD/.runtime/micromamba.tar.bz2"
curl --fail --location --retry 3 --connect-timeout 30 --max-time 600 \
  "https://conda.anaconda.org/conda-forge/$platform/micromamba-2.10.0-0.tar.bz2" -o "$archive"
if command -v shasum >/dev/null; then
  actual=$(shasum -a 256 "$archive" | cut -d ' ' -f 1)
else
  actual=$(sha256sum "$archive" | cut -d ' ' -f 1)
fi
if [ "$actual" != "$digest" ]; then printf '%s\n' 'Installer checksum mismatch; no downloaded executable was run.'; exit 1; fi
tar -xjf "$archive" -C .runtime bin/micromamba
export MAMBA_ROOT_PREFIX="$PWD/.runtime/mamba"
export XDG_CACHE_HOME="$PWD/.runtime/cache"
export CONDA_PKGS_DIRS="$PWD/.runtime/mamba/pkgs"
# A retry repairs an existing environment rather than touching analysis data.
action=create
if [ -d .runtime/env/conda-meta ]; then action=install; fi
.runtime/bin/micromamba "$action" --yes --no-rc --override-channels --channel conda-forge \
  --prefix "$PWD/.runtime/env" 'python=3.12' 'perl=5.32.1' pip
export PATH="$PWD/.runtime/env/bin:$PATH"
export PIP_CACHE_DIR="$PWD/.runtime/pip-cache"
.runtime/env/bin/python -m pip install --disable-pip-version-check -r packaging/requirements.txt
.runtime/env/bin/python packaging/install_tools.py .tools
source packaging/runtime.sh
"$runner" packaging/check_runtime.py
printf '%s\n' 'Setup complete. Future launches reuse these tools; reference genomes download when selected.'

}
install_runtime 2>&1 | tee -a .runtime/setup.log
