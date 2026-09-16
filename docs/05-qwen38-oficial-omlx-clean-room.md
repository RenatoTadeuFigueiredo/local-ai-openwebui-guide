# Qwen3.8-27B derivado do oficial: caminho clean-room recomendado

**Data de referência:** 27 de agosto de 2026  
**Hardware-alvo:** Apple M3 Max, GPU de 40 núcleos, 128 GB de memória unificada  
**Objetivo:** instalar um Qwen3.8-27B local com oMLX, Lightning MTP e contexto nativo de 262144 sem requantização local

> O guia executável completo está em [`../examples/qwen38-official-omlx/README.md`](../examples/qwen38-official-omlx/README.md). Este arquivo é a entrada curta do índice de documentação.

---

## Recomendação

Use o bundle [`../examples/qwen38-official-omlx/`](../examples/qwen38-official-omlx/) para baixar e executar:

```text
fcmeyer/Qwen3.8-27B-MLX-oQ4e-mtp
@ 02993567061709709fd60b38d64819e2b8f647a3
```

Esse checkpoint:

- declara `Qwen/Qwen3.8-27B` como base;
- é uma quantização comunitária oQ4e, não um checkpoint publicado pela equipe Qwen;
- mantém a cabeça MTP nativa;
- ocupa aproximadamente 17 GB;
- usa licença Apache-2.0 declarada no Hub;
- é baixado pronto, sem converter os ~56 GB do BF16 no Mac.

O bundle fixa a revisão, o SHA-256 do wheel oMLX, os hashes dos quatro shards e identidades dos metadados selecionados; gera credenciais locais e expõe somente uma API OpenAI-compatible em `127.0.0.1:8084`. As demais wheels PyPI são presas por versão, mas ainda não por hash — consulte a limitação de supply chain no guia completo.

---

## Instalação mínima

Pré-condição: obtenha uma cópia confiável/versionada do workspace. Este documento local ainda não fornece URL de release/commit nem checksum externo do próprio bundle; ao compartilhá-lo, publique um archive assinado ou commit/tag imutável com SHA-256.

```bash
brew install python@3.12
cd examples/qwen38-official-omlx
./install.sh --target "$HOME/models/qwen38-official-omlx"
"$HOME/models/qwen38-official-omlx/qwen38-official" start
"$HOME/models/qwen38-official-omlx/qwen38-official" chat \
  "Responda somente: OK"
```

Antes de usar 256K em clientes, execute o canário próprio do checkpoint novo:

```bash
PROFILE="$HOME/models/qwen38-official-omlx"
"$PROFILE/runtime/venv/bin/python" "$PROFILE/context-canary.py" \
  --prompt-tokens 40000 --max-tokens 4 --require-mtp
```

O procedimento completo, incluindo hardware, disco, verificação, OpenCode, Open WebUI, LaunchAgent, escada de contexto e rollback 32768, está no README do bundle.

---

## Separação do histórico

[`01-estudo-de-caso-qwen38-m3-max.md`](01-estudo-de-caso-qwen38-m3-max.md) continua documentando o checkpoint diferente:

```text
pyros-vault/Qwen3.8-27B-Uncensored-oQ4e-mtp
@ 13ec62924c70a30973ea9f01094cb0a0fdc98e49
```

Portanto, não transfira automaticamente ao perfil `fcmeyer`:

- média de ~46,5 tok/s ou pico de ~50,6 tok/s;
- aceitação MTP medida;
- RSS observado;
- canários de 40K/245K/fronteira;
- avaliação de segurança ou qualidade.

O novo perfil deve passar seus próprios gates. Metadado de 262144 prova capacidade declarada; não prova qualidade de contexto longo.

---

## Integrações

| Cliente | Identidade nova |
|---|---|
| Controlador | `qwen38-official` |
| Model ID da API | `qwen38-official-omlx` |
| Diretório | `~/models/qwen38-official-omlx` |
| OpenCode | `qwen38-official/qwen38-official-omlx` |
| Open WebUI com prefixo `local` | `local.qwen38-official-omlx` |
| API | `http://127.0.0.1:8084/v1` |

O runbook sem VPS, [`02-open-webui-sem-vps-macos-cloudflare.md`](02-open-webui-sem-vps-macos-cloudflare.md), registra a implantação uncensored existente e não deve ser reescrito como se a migração já tivesse ocorrido. O runbook com VPS, [`03-open-webui-com-vps-cloudflare.md`](03-open-webui-com-vps-cloudflare.md), usa o perfil oficial derivado como padrão para novas implantações.
