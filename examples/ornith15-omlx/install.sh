#!/usr/bin/env bash
# Clean-room install of the ornith15-omlx profile: pinned checkpoint, isolated
# runtime, verifier, no local re-quantisation.
set -euo pipefail

PROFILE_REPO="mlx-works/Ornith-1.5-9B-oQ4e-mtp"
PROFILE_REVISION="f6012213916a7df42640539c1df7cd031b2569fb"
WHEEL_NAME="omlx-0.6.3rc1-cp312-cp312-macosx_15_0_universal2.whl"
WHEEL_SHA256="7010ff68df48d38f17dde034fd6f3c2dd6c6c872bed29d42513506de4734362c"
WHEEL_URL="https://github.com/jundot/omlx/releases/download/v0.6.3rc1/$WHEEL_NAME"
TARGET="${ORNITH15_PROFILE_ROOT:-$HOME/models/ornith15-omlx}"
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKIP_HARDWARE=0
SKIP_DOWNLOAD=0
PORT=8086

usage() {
  cat <<EOF
usage: ./install.sh [--target PATH] [--skip-hardware-check] [--skip-download]

Installs the pinned profile at: $TARGET
--skip-download exists for tests/restore with model/ already populated.
Existing targets are refused; advanced repair needs ORNITH15_ALLOW_IN_PLACE_REPAIR=1.
EOF
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; TARGET="$2"; shift 2 ;;
    --skip-hardware-check) SKIP_HARDWARE=1; shift ;;
    --skip-download) SKIP_DOWNLOAD=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
TARGET="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$TARGET")"

if [[ "$SKIP_HARDWARE" -eq 0 ]]; then
  system_profiler -json SPHardwareDataType | python3 -c '
import json,re,sys
h=(json.load(sys.stdin).get("SPHardwareDataType") or [{}])[0]
chip=str(h.get("chip_type"))
ram=re.search(r"\d+", str(h.get("physical_memory") or ""))
ram_gb=int(ram.group()) if ram else 0
if "Apple M" not in chip or ram_gb < 32:
    raise SystemExit(f"hardware not validated: chip={chip!r}, memory={ram_gb} GB; expected Apple Silicon with 32 GB or more")
print(f"hardware: {chip}, {ram_gb} GB")
'
else
  echo "WARNING: hardware gate skipped; the measured case is an M3 Max with 128 GB."
fi

MACOS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
[[ "$MACOS_MAJOR" =~ ^[0-9]+$ && "$MACOS_MAJOR" -ge 15 ]] || {
  echo "macOS 15 or later is required by the pinned wheel" >&2; exit 1;
}
command -v python3.12 >/dev/null 2>&1 || {
  echo "python3.12 not found. Install it with: brew install python@3.12" >&2; exit 1;
}
command -v git >/dev/null 2>&1 || {
  echo "git not found. Install the Command Line Tools: xcode-select --install" >&2; exit 1;
}
if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port $PORT is already in use; stop the other profile first" >&2
  exit 1
fi
if launchctl print "gui/$(id -u)/com.local.ornith-omlx" >/dev/null 2>&1; then
  echo "LaunchAgent com.local.ornith-omlx is already loaded; boot it out first" >&2
  exit 1
fi

DISK_PROBE="$TARGET"
while [[ ! -e "$DISK_PROBE" ]]; do
  PARENT="$(dirname "$DISK_PROBE")"
  [[ "$PARENT" != "$DISK_PROBE" ]] || break
  DISK_PROBE="$PARENT"
done
FREE_KIB="$(df -Pk "$DISK_PROBE" | awk 'END{print $4}')"
if [[ ! -e "$TARGET" ]]; then
  MIN_KIB=$((55 * 1024 * 1024))
  if (( FREE_KIB < MIN_KIB )); then
    echo "not enough free space on the target volume: at least 55 GiB required" >&2
    echo "(model ~6.2 GiB, runtime ~1.5 GiB, SSD cache up to 40 GB, operational margin)" >&2
    exit 1
  fi
fi

umask 077
EXPECTED_MARKER="$PROFILE_REPO@$PROFILE_REVISION"
if [[ -e "$TARGET" ]]; then
  if [[ "${ORNITH15_ALLOW_IN_PLACE_REPAIR:-0}" != "1" ]]; then
    echo "refusing in-place install/repair: use another --target for a transactional install" >&2
    echo "advanced operators may authorise same-revision repair with ORNITH15_ALLOW_IN_PLACE_REPAIR=1" >&2
    exit 1
  fi
  echo "WARNING: in-place repair authorised; a network/pip failure may leave the profile down" >&2
  if [[ -f "$TARGET/state/server.pid" ]]; then
    OLD_PID="$(<"$TARGET/state/server.pid")"
    if [[ "$OLD_PID" =~ ^[0-9]+$ ]] && kill -0 "$OLD_PID" 2>/dev/null; then
      echo "refusing to update the bundle: live PID recorded in state/server.pid" >&2
      exit 1
    fi
    rm -f "$TARGET/state/server.pid"
  fi
  if [[ ! -f "$TARGET/.ornith15-profile" ]]; then
    echo "refusing existing directory without a profile marker: $TARGET" >&2
    exit 1
  fi
  if [[ "$(<"$TARGET/.ornith15-profile")" != "$EXPECTED_MARKER" ]]; then
    echo "refusing marker from another checkpoint/revision in: $TARGET" >&2
    exit 1
  fi
fi
mkdir -p "$TARGET" "$TARGET/runtime" "$TARGET/state" "$TARGET/models"
printf '%s\n' "$EXPECTED_MARKER" > "$TARGET/.ornith15-profile"

BUNDLE_FILES=(
  README.md install.sh secure_server.py verify-model.py context-canary.py
  sandbox.sb serve.sh launchd-start.sh ornith15-omlx settings.template.json
  model_settings.json requirements-runtime.txt wire-open-webui.py
  com.local.ornith-omlx.plist.template
)
for name in "${BUNDLE_FILES[@]}"; do
  install -m 600 "$SOURCE/$name" "$TARGET/$name"
done
chmod 700 "$TARGET/serve.sh" "$TARGET/launchd-start.sh" "$TARGET/ornith15-omlx" "$TARGET/context-canary.py"
SOURCE_MANIFEST="$TARGET/SOURCE_MANIFEST.sha256"
: > "$SOURCE_MANIFEST"
for name in "${BUNDLE_FILES[@]}"; do
  HASH="$(shasum -a 256 "$TARGET/$name" | awk '{print $1}')"
  printf '%s  %s\n' "$HASH" "$name" >> "$SOURCE_MANIFEST"
done
chmod 600 "$SOURCE_MANIFEST"

WHEEL="$TARGET/runtime/$WHEEL_NAME"
if [[ ! -f "$WHEEL" ]] || ! printf '%s  %s\n' "$WHEEL_SHA256" "$WHEEL" | shasum -a 256 -c - >/dev/null 2>&1; then
  rm -f "$WHEEL" "$WHEEL.partial"
  echo "downloading oMLX $WHEEL_NAME"
  curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
    --output "$WHEEL.partial" "$WHEEL_URL"
  printf '%s  %s\n' "$WHEEL_SHA256" "$WHEEL.partial" | shasum -a 256 -c -
  mv "$WHEEL.partial" "$WHEEL"
fi

VENV="$TARGET/runtime/venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  python3.12 -m venv "$VENV"
fi
"$VENV/bin/python" -m ensurepip --upgrade >/dev/null
PIP_DISABLE_PIP_VERSION_CHECK=1 "$VENV/bin/python" -m pip install --upgrade 'pip==26.0.1'
PIP_DISABLE_PIP_VERSION_CHECK=1 "$VENV/bin/python" -m pip install -r "$TARGET/requirements-runtime.txt"
PIP_DISABLE_PIP_VERSION_CHECK=1 "$VENV/bin/python" -m pip install --no-deps "$WHEEL"
"$VENV/bin/python" -m pip check

MODEL="$TARGET/model"
if [[ "$SKIP_DOWNLOAD" -eq 0 ]]; then
  mkdir -p "$MODEL"
  echo "downloading $PROFILE_REPO@$PROFILE_REVISION (~6.2 GB)"
  HF_HUB_DISABLE_TELEMETRY=1 "$VENV/bin/hf" download "$PROFILE_REPO" \
    --revision "$PROFILE_REVISION" \
    --local-dir "$MODEL" \
    --max-workers 4
else
  [[ -d "$MODEL" ]] || { echo "--skip-download requires $MODEL to be populated" >&2; exit 1; }
fi
printf '%s\n' "$PROFILE_REVISION" > "$TARGET/MODEL_REVISION"

TARGET_ENV="$TARGET" "$VENV/bin/python" - <<'PY'
import json,os,secrets
from pathlib import Path
root=Path(os.environ["TARGET_ENV"])
state=root/"state"
state.mkdir(mode=0o700,parents=True,exist_ok=True)
settings=json.loads((root/"settings.template.json").read_text())
settings["model"]["model_dirs"]=[str(root/"models")]
settings["model"]["model_dir"]=str(root/"models")
settings["cache"]["ssd_cache_dir"]=str(state/"cache")
(state/"settings.json").write_text(json.dumps(settings,indent=2,ensure_ascii=False)+"\n")
(state/"model_settings.json").write_bytes((root/"model_settings.json").read_bytes())
api=state/"api-key"
secret=state/"secret-key"
if not api.exists(): api.write_text(secrets.token_hex(32)+"\n")
if not secret.exists(): secret.write_text(secrets.token_hex(32)+"\n")
key=api.read_text().strip()
(state/"auth-header").write_text("Authorization: Bearer "+key+"\n")
for p in (state,state/"settings.json",state/"model_settings.json",api,secret,state/"auth-header"):
    p.chmod(0o700 if p.is_dir() else 0o600)
PY
mkdir -p "$TARGET/state/cache" "$TARGET/state/home" "$TARGET/state/hf-cache" "$TARGET/state/logs"
chmod 700 "$TARGET/state" "$TARGET/state/cache" "$TARGET/state/home" "$TARGET/state/hf-cache" "$TARGET/state/logs"
ln -sfn ../model "$TARGET/models/ornith15-omlx"

"$VENV/bin/python" "$TARGET/verify-model.py"

mkdir -p "$HOME/bin"
if [[ -e "$HOME/bin/ornith15-omlx" && ! -L "$HOME/bin/ornith15-omlx" ]]; then
  echo "did not replace $HOME/bin/ornith15-omlx because it is not a symlink" >&2
else
  ln -sfn "$TARGET/ornith15-omlx" "$HOME/bin/ornith15-omlx"
fi

cat <<EOF

Install validated.
Profile: $TARGET
Model:   ornith15-omlx
API:     http://127.0.0.1:$PORT/v1
Start:   $TARGET/ornith15-omlx start

Add $HOME/bin to PATH to use: ornith15-omlx start
EOF