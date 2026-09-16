#!/usr/bin/env bash
set -euo pipefail

PROFILE_REPO="fcmeyer/Qwen3.8-27B-MLX-oQ4e-mtp"
PROFILE_REVISION="02993567061709709fd60b38d64819e2b8f647a3"
WHEEL_NAME="omlx-0.6.3rc1-cp312-cp312-macosx_15_0_universal2.whl"
WHEEL_SHA256="7010ff68df48d38f17dde034fd6f3c2dd6c6c872bed29d42513506de4734362c"
WHEEL_URL="https://github.com/jundot/omlx/releases/download/v0.6.3rc1/$WHEEL_NAME"
TARGET="${QWEN38_PROFILE_ROOT:-$HOME/models/qwen38-official-omlx}"
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKIP_HARDWARE=0
SKIP_DOWNLOAD=0

usage() {
  cat <<EOF
uso: ./install.sh [--target PATH] [--skip-hardware-check] [--skip-download]

Instala o perfil fixado em: $TARGET
--skip-download existe somente para testes/restore com model/ já preenchido.
Targets existentes são recusados; reparo avançado exige QWEN38_ALLOW_IN_PLACE_REPAIR=1.
EOF
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; TARGET="$2"; shift 2 ;;
    --skip-hardware-check) SKIP_HARDWARE=1; shift ;;
    --skip-download) SKIP_DOWNLOAD=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; usage >&2; exit 2 ;;
  esac
done
TARGET="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$TARGET")"

if [[ "$SKIP_HARDWARE" -eq 0 ]]; then
  system_profiler -json SPHardwareDataType SPDisplaysDataType | python3 -c '
import json,re,sys
x=json.load(sys.stdin)
h=(x.get("SPHardwareDataType") or [{}])[0]
displays=x.get("SPDisplaysDataType") or []
chip=h.get("chip_type")
ram=h.get("physical_memory")
gpus=[str(g.get("sppci_cores")) for g in displays if g.get("sppci_cores") is not None]
ram_match=re.search(r"\d+", str(ram or ""))
ram_gb=int(ram_match.group()) if ram_match else 0
if chip != "Apple M3 Max" or ram_gb != 128 or "40" not in gpus:
    raise SystemExit(f"hardware não validado: chip={chip!r}, memória={ram!r}, GPUs={gpus!r}; esperado M3 Max/128 GB/GPU 40 cores")
print("hardware: Apple M3 Max, 128 GB, GPU 40 cores")
'
else
  echo "AVISO: hardware gate ignorado; o perfil 256K foi dimensionado para M3 Max/128 GB/40 GPU."
fi

MACOS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
[[ "$MACOS_MAJOR" =~ ^[0-9]+$ && "$MACOS_MAJOR" -ge 15 ]] || {
  echo "macOS 15 ou mais recente é necessário para o wheel fixado" >&2; exit 1;
}
if ! command -v python3.12 >/dev/null 2>&1; then
  echo "python3.12 não encontrado. Instale com: brew install python@3.12" >&2
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo "git não encontrado. Instale as Command Line Tools: xcode-select --install" >&2
  exit 1
fi
if lsof -tiTCP:8084 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "porta 8084 já está ocupada; pare o outro perfil antes da instalação clean-room" >&2
  exit 1
fi
if launchctl print "gui/$(id -u)/com.local.qwen38-official" >/dev/null 2>&1; then
  echo "LaunchAgent com.local.qwen38-official já está carregado; faça bootout antes" >&2
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
  MIN_KIB=$((70 * 1024 * 1024))
  if (( FREE_KIB < MIN_KIB )); then
    echo "espaço livre insuficiente no volume de destino: são exigidos pelo menos 70 GiB" >&2
    echo "(modelo/runtime ~18 GiB, cache SSD até 40 GB e margem operacional)" >&2
    exit 1
  fi
fi

umask 077
EXPECTED_MARKER="$PROFILE_REPO@$PROFILE_REVISION"
if [[ -e "$TARGET" ]]; then
  if [[ "${QWEN38_ALLOW_IN_PLACE_REPAIR:-0}" != "1" ]]; then
    echo "recusando instalação/reparo in-place: use outro --target para uma instalação transacional" >&2
    echo "operadores avançados podem autorizar reparo da mesma revisão com QWEN38_ALLOW_IN_PLACE_REPAIR=1" >&2
    exit 1
  fi
  echo "AVISO: reparo in-place autorizado; falha de rede/pip pode deixar o perfil indisponível" >&2
  if [[ -f "$TARGET/state/server.pid" ]]; then
    OLD_PID="$(<"$TARGET/state/server.pid")"
    if [[ "$OLD_PID" =~ ^[0-9]+$ ]] && kill -0 "$OLD_PID" 2>/dev/null; then
      echo "recusando atualizar o bundle: PID ativo registrado em state/server.pid" >&2
      exit 1
    fi
    rm -f "$TARGET/state/server.pid"
  fi
  if [[ ! -f "$TARGET/.qwen38-official-profile" ]]; then
    echo "recusando diretório existente sem marker do perfil: $TARGET" >&2
    exit 1
  fi
  if [[ "$(<"$TARGET/.qwen38-official-profile")" != "$EXPECTED_MARKER" ]]; then
    echo "recusando marker de outro checkpoint/revisão em: $TARGET" >&2
    exit 1
  fi
fi
mkdir -p "$TARGET" "$TARGET/runtime" "$TARGET/state" "$TARGET/models"
printf '%s\n' "$EXPECTED_MARKER" > "$TARGET/.qwen38-official-profile"

BUNDLE_FILES=(
  README.md install.sh secure_server.py verify-model.py set-context.py context-canary.py
  sandbox.sb serve.sh launchd-start.sh qwen38-official settings.template.json
  model_settings.json requirements-runtime.txt
  com.local.qwen38-official.plist.template
)
CONTROL_FILES=(
  install.sh secure_server.py verify-model.py set-context.py context-canary.py sandbox.sb
  serve.sh launchd-start.sh qwen38-official settings.template.json
  model_settings.json requirements-runtime.txt
  com.local.qwen38-official.plist.template
)
for name in "${BUNDLE_FILES[@]}"; do
  install -m 600 "$SOURCE/$name" "$TARGET/$name"
done
chmod 700 "$TARGET/serve.sh" "$TARGET/launchd-start.sh" "$TARGET/qwen38-official" \
  "$TARGET/set-context.py" "$TARGET/context-canary.py"
SOURCE_MANIFEST="$TARGET/SOURCE_MANIFEST.sha256"
: > "$SOURCE_MANIFEST"
for name in "${CONTROL_FILES[@]}"; do
  HASH="$(shasum -a 256 "$TARGET/$name" | awk '{print $1}')"
  printf '%s  %s\n' "$HASH" "$name" >> "$SOURCE_MANIFEST"
done
chmod 600 "$SOURCE_MANIFEST"

WHEEL="$TARGET/runtime/$WHEEL_NAME"
if [[ ! -f "$WHEEL" ]] || ! printf '%s  %s\n' "$WHEEL_SHA256" "$WHEEL" | shasum -a 256 -c - >/dev/null 2>&1; then
  rm -f "$WHEEL" "$WHEEL.partial"
  echo "baixando oMLX $WHEEL_NAME"
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
  echo "baixando $PROFILE_REPO@$PROFILE_REVISION (~17 GB)"
  HF_HUB_DISABLE_TELEMETRY=1 "$VENV/bin/hf" download "$PROFILE_REPO" \
    --revision "$PROFILE_REVISION" \
    --local-dir "$MODEL" \
    --max-workers 4
else
  [[ -d "$MODEL" ]] || { echo "--skip-download exige $MODEL já preenchido" >&2; exit 1; }
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
ln -sfn ../model "$TARGET/models/qwen38-official-omlx"

"$VENV/bin/python" "$TARGET/verify-model.py"

mkdir -p "$HOME/bin"
if [[ -e "$HOME/bin/qwen38-official" && ! -L "$HOME/bin/qwen38-official" ]]; then
  echo "não substituí $HOME/bin/qwen38-official porque não é symlink" >&2
else
  ln -sfn "$TARGET/qwen38-official" "$HOME/bin/qwen38-official"
fi

cat <<EOF

Instalação validada.
Perfil:  $TARGET
Modelo:  qwen38-official-omlx
API:     http://127.0.0.1:8084/v1
Iniciar: $TARGET/qwen38-official start

Adicione $HOME/bin ao PATH se quiser usar apenas: qwen38-official start
EOF
