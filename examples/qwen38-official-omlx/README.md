# Qwen3.8-27B derivado do oficial no M3 Max 128 GB

**Data de referência:** 27 de agosto de 2026  
**Hardware de referência/gate:** MacBook Pro com Apple M3 Max, GPU de 40 núcleos e 128 GB de memória unificada  
**Sistema/runtime:** macOS 15 ou mais recente, Python 3.12, oMLX `0.6.3rc1`  
**Modelo local:** `qwen38-official-omlx`  
**API:** `http://127.0.0.1:8084/v1`

Este é o guia clean-room recomendado para instalar, sem quantização local, uma quantização comunitária do modelo oficial `Qwen/Qwen3.8-27B`:

```text
fcmeyer/Qwen3.8-27B-MLX-oQ4e-mtp
@ 02993567061709709fd60b38d64819e2b8f647a3
```

O checkpoint de `fcmeyer` é público, Apache-2.0 e declara `Qwen/Qwen3.8-27B` como base. Ele **não é um checkpoint publicado pela equipe Qwen**; é um derivado quantizado por terceiro. Este bundle autentica exatamente a revisão e os arquivos derivados escolhidos, mas não prova equivalência tensor a tensor com o BF16 oficial.

> O estudo em [`../docs/01-estudo-de-caso-qwen38-m3-max.md`](../../docs/01-estudo-de-caso-qwen38-m3-max.md) mediu outro checkpoint, `pyros-vault/Qwen3.8-27B-Uncensored-oQ4e-mtp`. Os resultados de 46–50 tok/s, os canários 256K e o RSS registrados ali são históricos e **não são promessa de desempenho deste perfil**. Este guia começa uma instalação nova, com outro Model ID e outro diretório, sem substituir o perfil existente.

---

## 1. Resultado esperado

Ao terminar, a máquina terá:

- modelo oQ4e já quantizado, com aproximadamente 17 GB de payload e MTP nativo preservado;
- oMLX e dependências em venv Python 3.12 isolado;
- Lightning MTP habilitado com profundidade adaptativa de até 3 drafts;
- contexto nativo total de `262144` tokens;
- saída limitada autoritativamente a `8192` tokens e sempre sujeita a `prompt + saída <= contexto`;
- concorrência de uma requisição;
- cache persistente de prefixos limitado a `40GB` no SSD;
- API OpenAI-compatible somente em `127.0.0.1:8084`; cinco operações de estado/inferência exigem Bearer e `GET /health` permanece sem Bearer para liveness local;
- fachada com seis operações de inferência/estado, sem painel admin, MCP, download, quantização ou mutação de modelo;
- processo em modo offline e com rede de saída negada por `sandbox-exec`.

O perfil força o engine de **texto** (`llm`). Embora o checkpoint inclua a torre de visão, este procedimento não expõe entrada multimodal. Também não aplica YaRN nem amplia para 1M: `262144` é o limite nativo usado aqui.

### O que não está incluído

- requantização do BF16;
- Open WebUI, OpenCode ou Cloudflare instalados automaticamente;
- benchmark ou avaliação de qualidade;
- backup dos pesos/cache;
- isolamento completo do filesystem.

A política do sandbox é `allow default` + `deny network-outbound`: ela bloqueia egress, mas o processo ainda tem os acessos a arquivos concedidos ao usuário macOS. O `HOME` privado reduz descoberta acidental; não é um container nem uma fronteira contra o próprio usuário/root.

---

## 2. Identidades fixadas

| Componente | Identidade |
|---|---|
| Base declarada | `Qwen/Qwen3.8-27B` |
| Checkpoint executado | `fcmeyer/Qwen3.8-27B-MLX-oQ4e-mtp` |
| Revisão | `02993567061709709fd60b38d64819e2b8f647a3` |
| Licença declarada no Hub | Apache-2.0 |
| Payload indexado | `16971681484` bytes, cerca de 15,81 GiB |
| Shards | 4 safetensors, todos com SHA-256 fixado |
| Tensores MTP | 29 |
| Wheel | `omlx-0.6.3rc1-cp312-cp312-macosx_15_0_universal2.whl` |
| SHA-256 do wheel | `7010ff68df48d38f17dde034fd6f3c2dd6c6c872bed29d42513506de4734362c` |
| MLX | `0.32.0` |
| mlx-lm | `0.31.3` |
| mlx-metal | `0.32.0` |

O verificador também fixa tamanho e identidade dos metadados, arquitetura `qwen3_5`, RoPE nativo, tokenizer de 262144, quantização affine 4-bit/group 64, conjunto de 2209 tensores e fontes críticas instaladas do oMLX. Na instalação, ele grava `SOURCE_MANIFEST.sha256`; todos os starts verificam que o instalador, os scripts, configurações e templates operacionais continuam idênticos à cópia que passou pelo gate completo. O `README.md` instalado fica fora desse gate para poder receber anotações operacionais sem impedir o start.

**Limitação de supply chain:** o wheel e o checkpoint são autenticados; dependências Git estão presas a commits; as demais wheels PyPI estão presas por versão, mas ainda não por hash. O bundle não é um lock integral `pip --require-hashes` de todo `site-packages`. Instalação/pip e o verificador pré-start executam antes do sandbox e importam dependências; um pacote comprometido pode executar com os acessos do usuário. Para ambiente de ameaça elevada, gere e audite um wheelhouse por hashes, instale com `--no-index --require-hashes` e reduza dependências antes de usar este caminho.

---

## 3. Capacidade e disco

### Memória

Este perfil foi dimensionado especificamente para **128 GB**. A janela anunciada é capacidade máxima, não memória pré-alocada. O custo cresce conforme o contexto realmente preenchido aumenta.

Para esta arquitetura híbrida, uma estimativa útil do KV de atenção completa é cerca de:

| Contexto preenchido | KV de atenção aproximado |
|---:|---:|
| 32768 | 2 GiB |
| 65536 | 4 GiB |
| 131072 | 8 GiB |
| 262144 | 16 GiB |

Pesos, estado recorrente, primagem MTP, buffers de prefill e outros processos vêm além disso. O memory guard `safe` pode rejeitar/abortar uma requisição para preservar o sistema. Não eleve limites do Metal/macOS para forçar um canário.

### Disco

O instalador exige **70 GiB livres no volume de destino** em uma instalação nova:

- checkpoint + metadados: ~16 GiB;
- venv/runtime observado: ~1,1 GiB;
- cache SSD configurado: até `40GB` decimais, ~37,25 GiB;
- margem para download, logs e operação.

O cache cresce sob demanda. Ele não reserva 40 GB de RAM e não torna um prefill de 256K instantâneo. Não inclua `state/cache/` nem o venv em backup normal: são reconstruíveis. Preserve configuração, secrets owner-only e as identidades fixadas.

---

## 4. Pré-requisitos

Use o usuário normal que executará MLX/Metal. Não use `sudo` para instalar ou servir o perfil.

### 4.1 Conferir a máquina

```bash
sw_vers
uname -m
system_profiler SPHardwareDataType SPDisplaysDataType
df -h "$HOME"
```

Esperado:

```text
Chip: Apple M3 Max
Memory: 128 GB
Total Number of Cores (GPU): 40
Architecture: arm64
macOS: 15 ou mais recente
```

O instalador faz esse gate novamente e falha se o hardware não for exatamente o alvo. `--skip-hardware-check` existe para desenvolvimento controlado, não para o caminho recomendado.

### 4.2 Command Line Tools, Homebrew e Python 3.12

Se necessário:

```bash
xcode-select --install
```

Depois:

```bash
brew install python@3.12
python3.12 --version
git --version
command -v python3.12
command -v git
```

O wheel fixado exige macOS 15+ e CPython 3.12. Não use o Python global 3.13/3.14 para este runtime.

### 4.3 Porta

```bash
lsof -nP -iTCP:8084 -sTCP:LISTEN
```

A saída deve estar vazia. Se outro perfil já usa `8084`, pare-o deliberadamente ou escolha uma migração com downtime. Não altere apenas uma ocorrência da porta: o bundle a fixa em launcher, configuração, fachada e verificador.

---

## 5. Instalação clean-room

Execute a partir da raiz de uma **cópia confiável/versionada deste workspace**:

```bash
cd qwen38-official-omlx
./install.sh --target "$HOME/models/qwen38-official-omlx"
```

Este diretório local ainda não está publicado como release/commit externo neste guia; portanto, a primeira aquisição do bundle não é reproduzível apenas pelas URLs abaixo. Ao compartilhá-lo, distribua um archive assinado ou uma URL de commit/tag imutável com SHA-256 e registre esse valor junto ao guia. `SOURCE_MANIFEST.sha256` protege a cópia **depois** da instalação, mas não autentica a origem inicial.

O fluxo:

1. valida hardware, macOS, ferramentas e espaço;
2. baixa o wheel do release GitHub e verifica SHA-256;
3. cria o venv Python 3.12 e instala versões fixadas;
4. baixa a revisão imutável do checkpoint (~17 GB) diretamente para `model/`;
5. gera API key e secret de sessão aleatórios em `state/`, modo `0600`;
6. materializa configuração 256K coerente;
7. executa a verificação criptográfica completa, incluindo os quatro shards;
8. cria o symlink opcional `~/bin/qwen38-official`.

O repositório do modelo é público e não requer token Hugging Face. Não use `--skip-download` numa instalação normal; ele existe apenas para restore/testes cujo conteúdo será autenticado pelo verificador.

### 5.1 Resultado esperado

```text
Instalação validada.
Perfil:  .../models/qwen38-official-omlx
Modelo:  qwen38-official-omlx
API:     http://127.0.0.1:8084/v1
```

A verificação completa relê e calcula hashes de ~17 GB; ela pode levar alguns minutos.

### 5.2 PATH opcional

O symlink já fica em `~/bin`. Se esse diretório não estiver no PATH, adicione uma única vez:

```bash
grep -F 'export PATH="$HOME/bin:$PATH"' "$HOME/.zshrc" >/dev/null 2>&1 || \
  printf '\nexport PATH="$HOME/bin:$PATH"\n' >> "$HOME/.zshrc"
source "$HOME/.zshrc"
command -v qwen38-official
```

Sem alterar o shell, use o caminho absoluto:

```bash
PROFILE="$HOME/models/qwen38-official-omlx"
"$PROFILE/qwen38-official" status
```

---

## 6. Verificação antes do primeiro start

```bash
PROFILE="$HOME/models/qwen38-official-omlx"

cat "$PROFILE/.qwen38-official-profile"
cat "$PROFILE/MODEL_REVISION"
"$PROFILE/runtime/venv/bin/python" -m pip check
"$PROFILE/qwen38-official" verify
```

As duas primeiras saídas devem conter a revisão fixada. O último comando é a verificação criptográfica completa.

Para o gate estrutural rápido usado em cada start:

```bash
"$PROFILE/qwen38-official" verify --quick
```

`--quick` valida versões, estrutura, tamanhos, configuração, isolamento, rotas e regressões dos guards, mas não recalcula todos os hashes dos 17 GB. Use a verificação completa após instalação, restore, cópia ou suspeita de corrupção.

---

## 7. Primeiro start e smoke test

### 7.1 Iniciar

```bash
qwen38-official start
qwen38-official status
```

O primeiro comando espera até o modelo estar carregado. Não interprete apenas `/health` como pronto; o controlador exige `qwen38-official-omlx` em `loaded_models`.

### 7.2 Conferir bind e modelo anunciado

```bash
PROFILE="$HOME/models/qwen38-official-omlx"

lsof -nP -iTCP:8084 -sTCP:LISTEN
curl --fail --silent --show-error \
  -H @"$PROFILE/state/auth-header" \
  http://127.0.0.1:8084/v1/models \
  | python3 -m json.tool

curl --fail --silent --show-error \
  -H @"$PROFILE/state/auth-header" \
  http://127.0.0.1:8084/v1/models/status \
  | python3 -m json.tool
```

Exigir:

- listener exclusivamente em `127.0.0.1:8084`;
- Model ID `qwen38-official-omlx`;
- `max_model_len: 262144`;
- `model_context_length: 262144`;
- `max_context_window: 262144`;
- `max_tokens: 8192`;
- engine/model type de texto.

Falhar se houver `0.0.0.0:8084`, `*:8084` ou `[::]:8084`.

### 7.3 Smoke funcional

```bash
qwen38-official chat "Responda somente com a palavra OK."
```

Depois confirme Lightning MTP no log:

```bash
grep -E 'Speculative backend selected.*Lightning MTP|MTP path activated|MTP\[' \
  "$PROFILE/state/logs/server.log" | tail -10
```

Exigir uma seleção `Lightning MTP (model_type=qwen3_5, active)` e evidência nova do request (`MTP path activated` + resumo `MTP[...]`). Configuração `mtp_enabled=true` sozinha não prova que o caminho foi usado.

### 7.4 Autenticação negativa

```bash
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  -H 'Content-Type: application/json' \
  http://127.0.0.1:8084/v1/chat/completions \
  --data '{
    "model":"qwen38-official-omlx",
    "messages":[{"role":"user","content":"teste"}],
    "max_tokens":1
  }'
```

Esperado: `401` ou `403`.

---

## 8. Validar contexto sem confundir metadado com capacidade

Há quatro níveis diferentes:

1. **integridade estrutural:** checkpoint e tokenizer declaram `262144`;
2. **runtime:** endpoints anunciam `262144`;
3. **inferência real acima de 32K:** um prompt >32768 é processado e gera saída;
4. **fronteira exata:** `prompt + saída = 262144` sem ultrapassagem interna.

O instalador prova 1 e o primeiro start prova 2. Execute 3 antes de promover 256K para clientes. O nível 4 é caro e opcional; não o trate como teste cotidiano.

### 8.1 Canário inicial recomendado: 40K

O script usa o tokenizer local, constrói exatamente a quantidade pedida de tokens, faz completion raw autenticada, exige contagens/finish coerentes e uso real de MTP no log. Execute sem outras requisições concorrentes para que a evidência MTP nova pertença inequivocamente ao canário:

```bash
PROFILE="$HOME/models/qwen38-official-omlx"
"$PROFILE/runtime/venv/bin/python" "$PROFILE/context-canary.py" \
  --prompt-tokens 40000 \
  --max-tokens 4 \
  --require-mtp \
  | tee "$PROFILE/state/context-canary-40k.json"
```

Monitore em outro terminal:

```bash
qwen38-official status
memory_pressure
```

Esse teste pode levar vários minutos. Exija:

- `server_prompt_tokens: 40000`;
- `completion_tokens` entre 1 e 4;
- total no máximo 40004;
- `fresh_mtp_log_evidence: true`;
- serviço saudável ao final;
- nenhum `prefill_memory_aborted` ou `_MtpSafetyViolation`.

Ele prova capacidade acima de 32K no novo checkpoint; não prova qualidade de recall longo nem 256K cheio.

### 8.2 Escada opcional

Somente se 40K passar e houver necessidade real:

```bash
for TOKENS in 65536 131072 245760; do
  "$PROFILE/runtime/venv/bin/python" "$PROFILE/context-canary.py" \
    --prompt-tokens "$TOKENS" --max-tokens 1 \
    | tee "$PROFILE/state/context-canary-$TOKENS.json" || break
done
```

Pare no primeiro erro, memory guard, pressão severa ou latência inaceitável. Com concorrência 1, cada prefill monopoliza o modelo. Um canário de ~245K pode levar dezenas de minutos e deve ser executado conectado à energia, com workloads concorrentes fechados.

### 8.3 Fronteira exata opcional

```bash
"$PROFILE/runtime/venv/bin/python" "$PROFILE/context-canary.py" \
  --prompt-tokens 262143 --max-tokens 1 \
  | tee "$PROFILE/state/context-canary-boundary.json"
```

Esse teste exige exatamente `262143 + 1 = 262144`. Na posição final o guard pode reduzir MTP para decode comum; por isso a fronteira não usa `--require-mtp`. Não execute como simples smoke. Um sucesso prova admissão/posição naquele estado; não mede prefill frio se houver cache, nem qualidade semântica. A evidência MTP obrigatória já pertence ao canário 40K, onde há espaço para especulação.

---

## 9. Operação diária

```bash
qwen38-official start
qwen38-official status
qwen38-official chat "seu prompt"
qwen38-official restart
qwen38-official stop
```

Logs contínuos:

```bash
qwen38-official logs
qwen38-official launcher-logs
```

Use `Ctrl-C` para sair do `tail`; isso não para o servidor.

### Métricas

`qwen38-official status` mostra:

- requisições ativas/em fila;
- média de geração reportada pelo processo desde o start;
- memória usada/teto do modelo.

O comando `chat` também imprime o objeto `usage` retornado pelo request. Uma média global não equivale à velocidade de uma resposta específica; prompt, comprimento, aceitação MTP, contexto preenchido e temperatura alteram o resultado.

---

## 10. OpenCode

Esta seção foi verificada com OpenCode `1.18.23`. Ela presume que o CLI já foi instalado pelo método oficial escolhido pelo usuário; como canais de instalação mudam, consulte <https://opencode.ai/docs/>. Antes de configurar:

```bash
command -v opencode
opencode --version
```

Se a versão diferir, valide o JSON contra `https://opencode.ai/config.json` e revise as notas de migração. A integração usa o endpoint OpenAI-compatible local. O exemplo abaixo evita gravar a API key literal no JSON: OpenCode expande `{file:...}` oficialmente.

Faça backup da configuração existente antes de mesclar o bloco:

```bash
mkdir -p "$HOME/.config/opencode"
cp -p "$HOME/.config/opencode/opencode.json" \
  "$HOME/.config/opencode/opencode.json.backup-$(date +%Y%m%d-%H%M%S)" \
  2>/dev/null || true
```

Em `~/.config/opencode/opencode.json` ou num `opencode.json` de projeto, **mescle**:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "qwen38-official": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Qwen3.8 27B derivado do oficial — oMLX local",
      "options": {
        "baseURL": "http://127.0.0.1:8084/v1",
        "apiKey": "{file:~/models/qwen38-official-omlx/state/api-key}",
        "timeout": 7200000,
        "chunkTimeout": 600000
      },
      "models": {
        "qwen38-official-omlx": {
          "name": "Qwen3.8 27B oQ4e + Lightning MTP",
          "limit": {
            "context": 262144,
            "output": 8192
          }
        }
      }
    }
  },
  "model": "qwen38-official/qwen38-official-omlx",
  "small_model": "qwen38-official/qwen38-official-omlx",
  "compaction": {
    "auto": true,
    "prune": true,
    "reserved": 16384
  },
  "permission": {
    "edit": "ask",
    "bash": {
      "*": "ask",
      "rm -rf *": "deny",
      "git reset --hard*": "deny",
      "git clean -fd*": "deny"
    },
    "task": "ask",
    "external_directory": "ask",
    "webfetch": "ask",
    "websearch": "ask"
  },
  "share": "disabled"
}
```

Por que `reserved: 16384`: até 8192 tokens podem ser usados pela saída; o restante é margem nominal para compactação/tool schemas. Não é uma reserva rígida no servidor. A fachada continua sendo a autoridade final e reduz/rejeita quando o prompt renderizado não deixa espaço.

Valide a sintaxe, descoberta e inferência sem imprimir a configuração resolvida — ela pode conter o conteúdo expandido do arquivo da key:

```bash
python3 -m json.tool "$HOME/.config/opencode/opencode.json" >/dev/null
opencode models qwen38-official --verbose
opencode run --model qwen38-official/qwen38-official-omlx \
  "Responda somente: OK"
```

No TUI, use `/models` para selecionar o modelo. A política acima nega alguns padrões destrutivos e exige aprovação para edição, shell, subagentes, diretórios externos e rede. `write` é tratado pelo controle `edit` na schema atual. Configurações de projeto/managed podem alterar ou sobrepor a global; revise `opencode.json` do repositório e a precedência antes de confiar no gate. Não use `--auto` apenas por ser inferência local.

### Tokens e velocidade no OpenCode

```bash
opencode stats --models
opencode stats --days 1 --models
```

`stats` mostra uso agregado persistido. Na versão `1.18.23`, não há painel oficial que combine, para a sessão corrente, consumo completo e tokens/s do servidor. Para velocidade por request, consulte o `usage` da API/logs do oMLX; `qwen38-official status` mostra uma média do processo, não uma sessão OpenCode isolada.

---

## 11. Open WebUI

Para uma instalação nova, escolha a hospedagem, mas trate este README como autoridade para o **modelo**:

- tudo no Mac: use [`../docs/02-open-webui-sem-vps-macos-cloudflare.md`](../../docs/02-open-webui-sem-vps-macos-cloudflare.md) somente para instalar/configurar Open WebUI, segurança, Tunnel e backup. **Substitua integralmente** as seções `qwen-omlx`/`qwen38-omlx`, integração 256K, autostart e rollback do modelo pelas seções 5–13 deste README; não execute os comandos/caminhos históricos do perfil uncensored;
- WebUI em VPS: [`../docs/03-open-webui-com-vps-cloudflare.md`](../../docs/03-open-webui-com-vps-cloudflare.md) já adota `qwen38-official-omlx` para o provedor local.

No Admin Panel:

```text
Admin Settings → Connections → OpenAI → Add Connection
```

Quando o Open WebUI roda **no mesmo Mac**:

```text
URL:       http://127.0.0.1:8084/v1
API Key:   conteúdo de ~/models/qwen38-official-omlx/state/api-key
Prefix ID: local
Model IDs (Filter): qwen38-official-omlx
ID resultante no Open WebUI: local.qwen38-official-omlx
```

Se o Open WebUI estiver em **Docker no mesmo Mac**, `127.0.0.1` aponta para o container, não para o host; use uma origem deliberada como `host.docker.internal` e preserve firewall/auth, ou prefira a instalação nativa do runbook. Se estiver na VPS, a URL será o hostname protegido pelo Tunnel/Access do runbook; mantenha Bearer e Service Auth separados.

O Model ID de conexão é `local.qwen38-official-omlx`. Se criar um workspace model/alias, use **o mesmo ID** `local.qwen38-official-omlx` e conceda `read` somente ao público/grupos desejados; depois valide com uma conta comum tanto o modelo-base retornado pela conexão quanto o workspace model. Se a versão do Open WebUI impedir alias com o mesmo ID, use outro ID explícito e atualize `CONTEXT_COMPACTION_MODEL` para ele — não deixe os dois nomes divergirem silenciosamente. Não configure a key no navegador e mantenha **Direct Connections** desligado.

### Compactação 256K

Configuração recomendada:

```dotenv
ENABLE_CONTEXT_COMPACTION=true
CONTEXT_COMPACTION_MODEL='local.qwen38-official-omlx'
CONTEXT_COMPACTION_TOKEN_THRESHOLD=245760
CONTEXT_COMPACTION_TOKEN_CAP=245760
CONTEXT_COMPACTION_RETENTION_PERCENTAGE=40
```

Persista os mesmos valores no Admin Panel e no workspace model, pois ConfigVars salvas podem prevalecer sobre o arquivo de ambiente.

`245760` deixa diferença nominal de 16384 até `262144`; até 8192 podem ser usados por saída e o restante absorve system prompt, Tools e erro de estimativa quando couber. Tools podem ser injetadas depois da estimativa. Portanto:

- compactação não garante que todo request será aceito;
- a saída pode ser reduzida;
- a fachada pode rejeitar se o prompt final consumir a janela;
- nunca configure Open WebUI como se o modelo aceitasse `262144` de **entrada mais** `8192` de saída.

Antes de oferecer o modelo a outros usuários, valide pelo proxy do WebUI: descoberta, streaming, ACL, compactação e um prompt acima de 32K no checkpoint novo.

---

## 12. Autostart opcional com LaunchAgent

Primeiro conclua instalação, verificação e smoke manual. Depois pare o controlador:

```bash
qwen38-official stop
```

Gere o plist com `plistlib` — inclusive se o target tiver caracteres que exigem escape XML — sem editar placeholders manualmente:

```bash
PROFILE="$HOME/models/qwen38-official-omlx"
PLIST="$HOME/Library/LaunchAgents/com.local.qwen38-official.plist"
mkdir -p "$HOME/Library/LaunchAgents"

python3 - "$PROFILE" "$PLIST" <<'PY'
import pathlib,plistlib,sys
root=pathlib.Path(sys.argv[1]).resolve()
out=pathlib.Path(sys.argv[2])
plist={
    "Label":"com.local.qwen38-official",
    "ProgramArguments":[str(root/"launchd-start.sh")],
    "RunAtLoad":True,
    "ThrottleInterval":30,
    "ProcessType":"Interactive",
    "WorkingDirectory":str(root),
    "StandardOutPath":str(root/"state/launchd.out.log"),
    "StandardErrorPath":str(root/"state/launchd.err.log"),
}
with out.open("wb") as target:
    plistlib.dump(plist,target,fmt=plistlib.FMT_XML,sort_keys=False)
out.chmod(0o600)
PY

plutil -lint "$PLIST"
launchctl bootstrap "gui/$(id -u)" "$PLIST"
```

O LaunchAgent inicia após login do usuário, não antes. Aguarde e valide:

```bash
launchctl print "gui/$(id -u)/com.local.qwen38-official"
qwen38-official status
```

Com o LaunchAgent instalado:

- `qwen38-official status`, `logs`, `chat` e `verify` continuam válidos;
- `qwen38-official restart` usa `launchctl kickstart`;
- `start`/`stop` recusam lifecycle paralelo para evitar dois supervisores;
- o template não usa `KeepAlive`: um crash não reinicia automaticamente. Isso evita restart loop do modelo pesado; monitore o job e faça `kickstart` deliberado se quiser recuperação.

Parar e remover o autostart, sem apagar o modelo:

```bash
launchctl bootout "gui/$(id -u)/com.local.qwen38-official"
rm "$HOME/Library/LaunchAgents/com.local.qwen38-official.plist"
```

Isso não é destrutivo para o perfil. Após remover o plist, `qwen38-official start` volta a ser a autoridade manual.

---

## 13. Rollback para 32K

Use rollback se 256K produzir pressão, latência ou monopolização incompatíveis com o uso real. Defina uma vez nesta seção:

```bash
PROFILE="$HOME/models/qwen38-official-omlx"
```

### Manual

```bash
qwen38-official stop
qwen38-official context 32768
qwen38-official start
```

Se launchd estiver instalado:

```bash
launchctl bootout "gui/$(id -u)/com.local.qwen38-official"
qwen38-official context 32768
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.local.qwen38-official.plist"
```

Não deixe o job apenas carregado/inativo durante a alteração: `context` exige porta livre **e** label descarregada para impedir um restart concorrente.

`context` altera transacionalmente os dois JSONs e só conclui se o verificador rápido passar. O checkpoint/tokenizer continuam nativos em 262144; somente o teto operacional vira 32768.

Depois exija:

```bash
curl --fail --silent --show-error \
  -H @"$PROFILE/state/auth-header" \
  http://127.0.0.1:8084/v1/models | python3 -m json.tool
```

`max_model_len` deve ser `32768`. Rode também:

```bash
qwen38-official chat "Responda somente: OK"
```

Ajuste os clientes antes de reabrir uso normal:

- OpenCode: em `qwen38-official-omlx.limit`, `context: 32768`; em `compaction`, `reserved: 8192` ou mais. Valide com `opencode models qwen38-official --verbose` e um `opencode run` curto;
- Open WebUI: threshold/cap globais e persistidos para `24000`; workspace model `local.qwen38-official-omlx` com contexto `32768`. Reinicie e valide `/v1/models` pelo proxy, compactação e chat com conta comum.

Voltar ao nativo exige restaurar **servidor e clientes**:

```bash
qwen38-official stop
qwen38-official context 262144
qwen38-official start
qwen38-official chat "Responda somente: OK"
```

Depois restaure OpenCode para `context: 262144`/`reserved: 16384`; restaure Open WebUI e workspace model para threshold/cap `245760` e contexto `262144`; reinicie e repita os gates de descoberta, compactação, ACL e chat. No modo 262144, o script garante cache SSD configurado em `40GB`. Não apague `state/cache/` com `rm -rf` durante rollback; deixe o gerenciador aplicar seu teto.

---

## 14. Atualização e restore

Não troque silenciosamente branch, revisão, wheel ou dependências. Este bundle é um perfil congelado. Antes de reexecutar `install.sh` sobre um perfil válido, obtenha uma cópia confiável do bundle correspondente: o manifest detecta drift relativo à cópia instalada, mas não substitui uma assinatura externa da origem; wheel/checkpoint e fontes críticos do oMLX têm os gates adicionais descritos acima.

Antes de atualizar:

1. parar/unload do LaunchAgent;
2. preservar configuração e secrets owner-only;
3. criar outro diretório de perfil;
4. revisar release notes e recalcular/fixar identidades;
5. instalar e testar em porta separada ou janela de manutenção;
6. promover apenas após smoke, MTP, contexto e clientes passarem.

### O que guardar

Guarde cifrado:

- `.qwen38-official-profile`, `MODEL_REVISION` e `SOURCE_MANIFEST.sha256`;
- scripts/templates deste bundle, incluindo `install.sh`;
- `state/settings.json` e `state/model_settings.json`;
- `state/api-key`, `state/secret-key` e `state/auth-header`;
- resultados dos canários que você executou;
- plist final, se houver.

Os pesos podem ser baixados novamente pela revisão e autenticados pelos hashes. Venv e cache também são reconstruíveis. Se o requisito for recuperação sem Internet/Hub, mantenha cópia cifrada dos quatro shards e wheel em storage independente e valide `qwen38-official verify` após restaurar.

Por padrão, o instalador recusa qualquer target já existente: instale/atualize em outro diretório, valide e promova deliberadamente. Um reparo in-place da mesma revisão requer autorização explícita `QWEN38_ALLOW_IN_PLACE_REPAIR=1`, marker exato e perfil/LaunchAgent parado; ele continua não sendo transacional e pode deixar indisponibilidade se pip/rede falhar. Diretórios arbitrários ou marker de outra revisão são sempre recusados.

---

## 15. Remoção segura

Remover o perfil apaga pesos, venv, cache e keys. Isso é destrutivo; faça backup do que precisa e confirme o caminho antes.

1. descarregue o LaunchAgent ou pare manualmente;
2. remova o symlink `~/bin/qwen38-official` se ele apontar para este perfil;
3. arquive/rotacione as keys usadas por OpenCode/Open WebUI;
4. remova as conexões dos clientes;
5. só então exclua `~/models/qwen38-official-omlx` deliberadamente.

Este guia não fornece um comando automático de remoção para evitar apagar um target errado.

---

## 16. Checklist de aceitação

### Instalação

- [ ] hardware é M3 Max / 40 GPU / 128 GB;
- [ ] macOS é 15+ e Python é 3.12;
- [ ] há ao menos 70 GiB livres no volume de destino;
- [ ] revisão do checkpoint é `02993567061709709fd60b38d64819e2b8f647a3`;
- [ ] SHA-256 do wheel confere;
- [ ] `pip check` passa;
- [ ] verificação criptográfica completa passa;
- [ ] nenhum secret foi colocado no Git, shell history ou screenshot.

### Serviço

- [ ] listener é somente `127.0.0.1:8084`;
- [ ] request sem Bearer é negado;
- [ ] `/v1/models` anuncia `qwen38-official-omlx` e contexto esperado;
- [ ] smoke retorna conteúdo;
- [ ] log prova Lightning MTP ativo no request;
- [ ] processo não possui egress;
- [ ] somente as seis rotas da fachada estão expostas;
- [ ] não há outro perfil na porta 8084.

### Contexto

- [ ] canário 40K passou no checkpoint novo;
- [ ] memória/TTFT foram observados e aceitos;
- [ ] escada profunda foi executada apenas se necessária;
- [ ] OpenCode/Open WebUI usam `prompt + output`, não 262K + 8K;
- [ ] clientes têm compactação/margem configuradas;
- [ ] rollback 32768 foi ensaiado antes de depender de 256K em produção.

### Clientes

- [ ] OpenCode usa `{file:...}`, não key literal;
- [ ] OpenCode resolve contexto 262144 e saída 8192;
- [ ] Open WebUI usa conexão server-to-server, sem Direct Connections;
- [ ] workspace model/ACL usam `local.qwen38-official-omlx`;
- [ ] streaming e compactação foram testados pelo caminho real;
- [ ] qualquer Tunnel preserva loopback e dupla autenticação conforme o runbook.

---

## 17. Referências

- Qwen oficial: <https://huggingface.co/Qwen/Qwen3.8-27B>
- Checkpoint derivado fixado: <https://huggingface.co/fcmeyer/Qwen3.8-27B-MLX-oQ4e-mtp/tree/02993567061709709fd60b38d64819e2b8f647a3>
- oMLX `v0.6.3rc1`: <https://github.com/jundot/omlx/releases/tag/v0.6.3rc1>
- OpenCode — providers: <https://opencode.ai/docs/providers/>
- OpenCode — config e `{file:...}`: <https://opencode.ai/docs/config/>
- Open WebUI — provider OpenAI-compatible: <https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/>

---

## 18. Conclusão

Para uma máquina igual ao hardware de referência, o caminho mais simples e auditável é **baixar o oQ4e+MTP já pronto**, não baixar ~56 GB de BF16 e requantizar localmente. O bundle/guards foram validados estruturalmente nesse ambiente compatível, mas o checkpoint `fcmeyer` ainda requer o primeiro smoke e canário empíricos na instalação de destino. O perfil conserva a janela nativa de 262144, aplica limites fail-closed e mantém a API no loopback.

A recomendação permanece condicional a três gates distintos:

1. integridade do bundle/checkpoint;
2. inferência e MTP reais neste checkpoint;
3. qualidade e contexto representativos do uso de quem instalou.

Passar o primeiro gate não implica os outros dois. Em particular, os resultados históricos do modelo uncensored não devem ser atribuídos a este derivado oficial sem uma nova medição controlada.
