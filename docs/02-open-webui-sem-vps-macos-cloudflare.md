# Open WebUI sem VPS: macOS, Qwen local e Cloudflare Tunnel

**Status:** fluxo principal implantado e aprovado em 25 de agosto de 2026; perfil Qwen de 256K promovido e validado após o restart final em 27 de agosto de 2026; ainda pendem reboot físico/pós-login, cópia de desastre externa, confirmação do roteador e alertas operacionais  
**Versões instaladas:** Open WebUI `v0.11.0`; Python `3.12.14`; `cloudflared` `2026.8.2`  
**Objetivo:** executar o Open WebUI diretamente no Mac, acessar pelo celular em `https://chat.seudominio.com` sem VPN e usar `qwen38-omlx` por loopback  
**Autenticação escolhida:** `chat.seudominio.com` usa somente login/senha do Open WebUI, sem Cloudflare Access/OTP; o hostname separado `browser.seudominio.com` usa One-Time PIN exclusivamente para takeover HITL  
**Não usa:** VPS, Docker para o WebUI, `llm-home.seudominio.com`, Service Token ou exposição remota direta da API do Qwen

> Este é exclusivamente o cenário **sem VPS**. Para manter o WebUI e o OpenRouter disponíveis quando o Mac estiver desligado, use [`03-open-webui-com-vps-cloudflare.md`](03-open-webui-com-vps-cloudflare.md).
>
> **Proveniência do estado implantado:** `qwen38-omlx` neste runbook é o checkpoint uncensored `pyros-vault/...@13ec629…`, preservado como registro operacional. Para outra máquina ou instalação nova, a recomendação é o perfil separado `qwen38-official-omlx`, documentado em [`../examples/qwen38-official-omlx/README.md`](../examples/qwen38-official-omlx/README.md). Não troque IDs/caminhos neste documento sem executar e datar uma migração real.

## Convenções: substitua pelos seus valores

Os documentos descrevem uma implantação concreta. Os identificadores abaixo são **placeholders** — troque pelos seus:

| Placeholder | O que é |
|---|---|
| `seudominio.com` | Seu domínio próprio. Todos os subdomínios derivam dele: `chat.`, `browser.`, `llm-home.` |
| `admin` | O operador da máquina — você. É quem instala, tem acesso root-equivalente e enxerga os modelos privados |
| `user-a`, `user-b` | Demais usuários com acesso. Têm login próprio, perfil de navegador isolado e nenhum privilégio administrativo |
| `user-c`, `user-d` | Usuários previstos, ainda sem container opcional |
| `cptr/admin` | ID do modelo privado, no formato `prefixo/nome` que o Open WebUI usa |

Nada disso é configuração a copiar literalmente: ao seguir o guia, gere os seus próprios segredos, escolha o seu domínio e crie as suas contas.

---

## 1. Garantia arquitetural e disponibilidade

Cloudflare Tunnel publica um processo que continua rodando no Mac; ele não hospeda esse processo na Cloudflare.

```text
Celular
  │ HTTPS + Cloudflare proxy
  ▼
Cloudflare Tunnel
  │
  ▼
Login nativo do Open WebUI 127.0.0.1:3000 no Mac
  ├── HTTP loopback + Bearer ──→ qwen-omlx 127.0.0.1:8084
  └── HTTPS opcional ──────────→ OpenRouter
```

### Quando o Mac estiver desligado

| Componente | Disponibilidade |
|---|:---:|
| `https://chat.seudominio.com` | não |
| Interface e histórico do Open WebUI | não |
| Qwen local | não remotamente |
| OpenRouter por essa interface | não |
| Dados locais em disco | preservados |

Mesmo que OpenRouter esteja operacional, não há interface para chamá-lo porque o próprio Open WebUI está desligado. Se continuidade sem o Mac for requisito, este é o cenário errado: escolha o runbook com VPS.

### Quando a internet ou Cloudflare estiver indisponível

O processo e o Qwen continuam no Mac, e a porta de manutenção permanece em:

```text
http://127.0.0.1:3000
```

Porém, depois do go-live os cookies estarão marcados `Secure` e o navegador não os enviará por HTTP. Portanto, **uso autenticado offline não é automático**. Há duas opções:

1. configurar HTTPS local confiável — mais conveniente, porém fora do escopo deste primeiro runbook; ou
2. com Tunnel/WebUI parados, alterar temporariamente os dois cookie flags para `false`, iniciar somente em loopback, usar localmente e restaurar `true` antes de reativar o Tunnel.

A autenticação nativa do Open WebUI torna essa recuperação possível; o origin não depende de headers de identidade do Cloudflare.

---

## 2. Domínio e serviços

| Item | Valor |
|---|---|
| WebUI público | `https://chat.seudominio.com` |
| WebUI local | `http://127.0.0.1:3000` |
| Qwen local | `http://127.0.0.1:8084/v1` |
| Model ID | `qwen38-omlx` |
| Tunnel | `openwebui-mac` |
| Apex reservado | `seudominio.com` e `www.seudominio.com` |

Estado público verificado em 25/08/2026:

- `seudominio.com` está delegado a `jacob.ns.cloudflare.com` e `connie.ns.cloudflare.com`;
- `chat.seudominio.com` é um CNAME proxied para o Tunnel `openwebui-mac`, sem `A`/`AAAA` residencial;
- o Tunnel está `healthy`, com conexões HA prontas;
- `llm-home.seudominio.com` não existe;
- nenhum MX está publicado para `seudominio.com`.

O hostname **`chat.seudominio.com`** não usa Cloudflare Access nesta implantação. A aplicação OTP criada depois protege exclusivamente `browser.seudominio.com` e não cobre nem herda para o chat. Há cinco contas internas conhecidas: um admin e quatro contas comuns. Signup público está desabilitado; novas contas só devem ser provisionadas deliberadamente por um administrador. A tela de login é pública e protegida por senha forte, rate limiting no edge e pelo limitador interno do Open WebUI.

### Regra fundamental

Somente o Open WebUI será publicado. Não crie:

- `llm-home.seudominio.com` neste cenário;
- registro `A`/`AAAA` para o IP residencial;
- port forwarding no roteador;
- bind `0.0.0.0` para Open WebUI ou Qwen;
- conexão direta do navegador com `8084`.

---

## 3. Pré-requisitos

No Mac:

- macOS em Apple Silicon;
- Python 3.11 ou 3.12 — Open WebUI não suporta 3.13 nesta versão;
- domínio `seudominio.com` ativo na Cloudflare;
- conta Cloudflare Zero Trust;
- `qwen-omlx` já instalado e verificável;
- espaço para banco, uploads e backups;
- password manager para credenciais;
- `cloudflared` somente quando chegar à fase do Tunnel.

Este guia escolhe instalação Python nativa porque:

- o WebUI e o Qwen compartilham o mesmo host;
- `127.0.0.1:8084` funciona diretamente;
- não há tradução `host.docker.internal`;
- não é necessário instalar Docker apenas para a interface.

Não reutilize o ambiente Python privado do oMLX. O Open WebUI terá seu próprio venv.

---

## 4. Layout isolado no Mac

```text
~/services/open-webui-mac/
├── app/                # venv Python
├── data/               # banco, uploads e configuração persistida
├── secrets/            # arquivos owner-only
├── backups/            # somente backups cifrados
├── env                 # configuração sem valores secretos
└── logs/               # stdout/stderr do LaunchAgent
```

Criar:

```bash
umask 077
mkdir -p ~/services/open-webui-mac/{app,data,secrets,backups,logs}
chmod 700 ~/services/open-webui-mac \
  ~/services/open-webui-mac/{app,data,secrets,backups,logs}
```

Não use `~/.open-webui` implicitamente; o caminho explícito simplifica backup e rollback.

---

## 5. Instalar Open WebUI em venv privado

> Esta seção registra os comandos executados na implantação. Em uma reinstalação, use um diretório/venv novo e restaure o banco somente depois de validar compatibilidade; não sobrescreva o ambiente funcional.

### 5.1 Criar o ambiente

A implantação real usou Python 3.12 do Homebrew:

```bash
brew install python@3.12
cd ~/services/open-webui-mac
/opt/homebrew/bin/python3.12 -m venv app/venv
source app/venv/bin/activate
python -m pip install --upgrade pip
python -m pip install 'open-webui==0.11.0'
python -c "from importlib.metadata import version; print(version('open-webui'))"
python -m pip check
```

O CLI `open-webui --version` não existe em `v0.11.0`; use metadata Python. Não deixe `python3` escolher a versão global 3.14/3.13, incompatível com este release.

### 5.2 Fixar dependências

Depois de validar a instalação:

```bash
python -m pip freeze > app/requirements-working.txt
shasum -a 256 app/requirements-working.txt \
  > app/requirements-working.txt.sha256
```

`pip freeze` registra o ambiente funcional, mas não é um lock integral com hashes de todas as wheels. Para reinstalação supply-chain mais forte, baixe wheels, registre hashes e use `--require-hashes` numa etapa posterior.

### 5.3 Gerar o segredo do WebUI

```bash
umask 077
openssl rand -hex 32 > secrets/webui-secret-key
chmod 600 secrets/webui-secret-key
```

Essa chave assina sessões e protege dados específicos suportados. Ela não deve ser interpretada como criptografia genérica das API keys persistidas nas conexões; trate `data/` e backups como secrets.

---

## 6. Configuração endurecida

Crie `~/services/open-webui-mac/env` com modo `0600`. O arquivo contém configuração, mas o segredo do WebUI continuará separado:

```dotenv
ENV=prod
UVICORN_WORKERS=1
DATA_DIR='/Users/SEU_USUARIO/services/open-webui-mac/data'
WEBUI_URL='https://chat.seudominio.com'
CORS_ALLOW_ORIGIN='https://chat.seudominio.com'
DEFAULT_USER_ROLE='pending'
ENABLE_SIGNUP='false'
ENABLE_INITIAL_ADMIN_SIGNUP='false'

ENABLE_PASSWORD_VALIDATION='true'
PASSWORD_VALIDATION_REGEX_PATTERN='^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{12,}$'
PASSWORD_VALIDATION_HINT='Mínimo de 12 caracteres com maiúscula, minúscula, número e símbolo.'
JWT_EXPIRES_IN='4h'

# Estado final ativo. O bootstrap headless não requer sessão HTTP no navegador.
WEBUI_SESSION_COOKIE_SECURE='true'
WEBUI_SESSION_COOKIE_SAME_SITE='strict'
WEBUI_AUTH_COOKIE_SECURE='true'
WEBUI_AUTH_COOKIE_SAME_SITE='strict'

HSTS='max-age=31536000;includeSubDomains'
XFRAME_OPTIONS='DENY'
XCONTENT_TYPE='nosniff'
REFERRER_POLICY='strict-origin-when-cross-origin'
PERMISSIONS_POLICY='camera=(),microphone=(),geolocation=()'

ENABLE_OLLAMA_API=false
ENABLE_OPENAI_API=true
ENABLE_OPENAI_API_PASSTHROUGH=false
ENABLE_DIRECT_CONNECTIONS=false
ENABLE_COMMUNITY_SHARING=false
# true somente para a Tool local auditada de Browser HITL; usuários comuns
# permanecem sem workspace.tools/import/export nas permissões persistidas.
ENABLE_PLUGINS=true
# obrigatório para que chaves server-side de Tools/Functions não fiquem em JSON claro
ENABLE_VALVE_ENCRYPTION=true
ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS=false
# O checkpoint/oMLX anuncia 262.144 tokens. O gatilho estimado em 245.760
# fornece margem nominal de 16.384; o facade garante prompt+saída no teto real.
ENABLE_CONTEXT_COMPACTION=true
CONTEXT_COMPACTION_MODEL='local.qwen38-omlx'
CONTEXT_COMPACTION_TOKEN_THRESHOLD=245760
CONTEXT_COMPACTION_TOKEN_CAP=245760
CONTEXT_COMPACTION_RETENTION_PERCENTAGE=40
ENABLE_CODE_EXECUTION=false
ENABLE_CODE_INTERPRETER=false
ENABLE_WEB_SEARCH=false
ENABLE_LOCAL_WEB_FETCH=false
ENABLE_AUTOMATIONS=false
ENABLE_SUBAGENTS=false
ENABLE_IMAGE_GENERATION=false
ENABLE_RAG_LOCAL_WEB_FETCH=false
ENABLE_PROFILE_IMAGE_URL_FORWARDING=false
ENABLE_API_KEYS=false
ENABLE_CHANNELS=false
ENABLE_CALENDAR=false
SAFE_MODE=true
ENABLE_VERSION_UPDATE_CHECK=false
RAG_EMBEDDING_MODEL_TRUST_REMOTE_CODE=false
RAG_EMBEDDING_MODEL_AUTO_UPDATE=false
RAG_EMBEDDING_MODEL=''
BYPASS_EMBEDDING_AND_RETRIEVAL=true
USER_AGENT='OpenWebUI-local/0.11.0 (chat.seudominio.com)'

RAG_FILE_MAX_SIZE=25
RAG_FILE_MAX_COUNT=5
RAG_ALLOWED_FILE_EXTENSIONS='pdf,txt,md,docx,csv'

AUDIT_LOG_LEVEL=METADATA
ENABLE_AUDIT_LOGS_FILE=true
AUDIT_LOG_FILE_ROTATION_SIZE=10MB
LOG_FORMAT=json
GLOBAL_LOG_LEVEL=INFO
AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST=5
```

Substitua `SEU_USUARIO` pelo resultado de `id -un`; não deixe o placeholder no arquivo real. As aspas simples são deliberadas: o arquivo será lido por `zsh`, e regex, `;` e parênteses não podem ficar como sintaxe solta do shell.

```bash
chmod 600 ~/services/open-webui-mac/env
zsh -n ~/services/open-webui-mac/env
```

### ConfigVar

Diversas configurações são persistidas no banco depois do primeiro start. Uma mudança posterior apenas no arquivo `env` pode não vencer o valor salvo. Depois de cada alteração, confira o estado efetivo no Admin Panel. Não desabilite persistent config sem entender que mudanças da UI deixarão de persistir.

Neste ambiente, a compactação automática também foi persistida em **Admin Panel → Settings → Interface**, com modelo `local.qwen38-omlx`, threshold/cap de `245760` e retenção de `40%`. O workspace model `local.qwen38-omlx` mantém `compact_token_threshold=245760`. O checkpoint e o tokenizer declaram um máximo nativo de `262144`, e o oMLX anuncia o mesmo valor como janela total de contexto. O threshold fornece `16384` tokens de **margem nominal**, não uma partição garantida: a estimativa ocorre antes de algumas injeções e pode reduzir a saída disponível. A fachada segura conta o prompt final renderizado e impõe autoritativamente `prompt + saída <= 262144`. A compactação grava um checkpoint-resumo e preserva as mensagens visíveis do chat.

---

## 7. Bootstrap local do administrador

### 7.1 Carregar configuração sem vazar o segredo em `argv`

Crie um launcher owner-only:

```bash
cat > ~/services/open-webui-mac/app/start-open-webui.sh <<'SH'
#!/bin/zsh
set -euo pipefail
umask 077
ROOT="$HOME/services/open-webui-mac"
set -a
source "$ROOT/env"
set +a
export WEBUI_SECRET_KEY="$(<"$ROOT/secrets/webui-secret-key")"
exec "$ROOT/app/venv/bin/open-webui" serve \
  --host 127.0.0.1 \
  --port 3000
SH
chmod 700 ~/services/open-webui-mac/app/start-open-webui.sh
```

O secret aparece no ambiente do processo, não na linha de comando. O mesmo usuário e root ainda podem lê-lo; isso é inerente ao processo. Não habilite shell tracing e não registre o ambiente.

### 7.2 Bootstrap headless usado na implantação

Foi gerada uma senha aleatória de 48 caracteres em arquivo `0600`, sem exibição no chat:

```bash
openssl rand -base64 36 | tr -d '\n' > ~/services/open-webui-mac/secrets/admin-password
chmod 600 ~/services/open-webui-mac/secrets/admin-password
```

Um launcher temporário carregou somente no primeiro start:

```bash
ROOT="$HOME/services/open-webui-mac"
export WEBUI_ADMIN_EMAIL='<EMAIL_ADMIN>'
export WEBUI_ADMIN_NAME='<NOME_ADMIN>'
export WEBUI_ADMIN_PASSWORD="$(<"$ROOT/secrets/admin-password")"
```

Após confirmar no banco exatamente um usuário `admin` no bootstrap, o serviço foi reiniciado com `start-open-webui.sh`, sem `WEBUI_ADMIN_PASSWORD` no ambiente permanente. `ENABLE_SIGNUP=false` permaneceu efetivo. A senha gerada passou pela regex de complexidade (`PASS`, sem exibir seu valor), foi usada no navegador e o clipboard foi limpo.

Depois de salvar a credencial no password manager e validar o login HTTPS, `secrets/admin-password` deve ser removido. O script de backup atual já exclui esse arquivo; backups antigos gerados antes desse hardening ainda podem conter a cópia bootstrap e exigem decisão explícita de retenção/remoção e possível rotação da senha.

### 7.3 Gate HTTPS antes da publicação

Edite o arquivo `env`:

```dotenv
WEBUI_SESSION_COOKIE_SECURE=true
WEBUI_AUTH_COOKIE_SECURE=true
```

A partir desse momento, use `https://chat.seudominio.com` no navegador. Cookies Secure não serão enviados a `http://127.0.0.1:3000`; para manutenção local, use um túnel SSH/HTTPS apropriado ou reverta temporariamente com o serviço parado e sem exposição pública.

---

## 8. Conectar o Qwen pelo loopback

### 8.1 Verificar e iniciar o modelo

```bash
qwen-omlx verify --quick
qwen-omlx start
qwen-omlx status
lsof -nP -iTCP:8084 -sTCP:LISTEN
```

O listener deve ser exatamente:

```text
127.0.0.1:8084
```

### 8.2 Testar sem expor a key no `argv`

```bash
umask 077
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT INT TERM
QWEN_KEY_FILE="$HOME/models/qwen38-omlx/state/api-key"

{
  printf 'silent\nshow-error\nfail-with-body\n'
  printf 'url = "http://127.0.0.1:8084/v1/models"\n'
  printf 'header = "Authorization: Bearer %s"\n' "$(<"$QWEN_KEY_FILE")"
} > "$TEST_DIR/qwen.curlrc"
chmod 600 "$TEST_DIR/qwen.curlrc"
curl --config "$TEST_DIR/qwen.curlrc"
```

Deve listar `qwen38-omlx` com `max_model_len=262144`. O checkpoint e o tokenizer permanecem nativos em `262144`; `state/settings.json` e `state/model_settings.json` devem concordar entre si no perfil efetivo permitido (`262144` ativo ou `32768` de rollback), e `qwen-omlx verify --quick` falha se esse conjunto ficar incoerente. A fachada segura transforma `8192` em teto real — não apenas default —, grava o valor reduzido no objeto da requisição antes de iniciar qualquer resposta diferida e garante `prompt + output <= 262144` em completion e chat completion. O MTP especulativo também reduz a profundidade junto ao limite e verifica os offsets reais dos caches alvo e da cabeça MTP, impedindo que um forward interno avance além da janela mesmo quando os tokens especulativos não seriam emitidos.

O cache persistente de prefixos usa até `40GB` em `~/models/qwen38-omlx/state/cache`. Isso não pré-aloca 40 GB de RAM nem torna o prefill de 256K instantâneo; é apenas o teto em SSD para reutilização de prefixos. A janela total maior aumenta memória e latência conforme o contexto realmente preenchido cresce.

### 8.3 Cadastrar no Open WebUI

```text
Admin Settings → Connections → OpenAI → Add Connection
```

Campos:

```text
URL:       http://127.0.0.1:8084/v1
API Key:   conteúdo de ~/models/qwen38-omlx/state/api-key
Prefix ID: local
Model IDs (Filter): qwen38-omlx
```

Não são necessários custom headers, Service Token nem Cloudflare entre WebUI e Qwen. Essa conexão é server-to-server no loopback do mesmo Mac.

A conexão é global, mas `v0.11.0` exige uma entrada de modelo com controle de acesso para usuários comuns. Em **Admin Settings → AI → Models**, marque `local.qwen38-omlx` como **Public** (`read` para `user:*`). Não configure a conexão/API key em cada conta e não habilite Direct Connections. **Selected** ou **Pinned** apenas muda a experiência inicial; não substitui a permissão Public.

### 8.4 Testar chat

1. selecionar o modelo local no WebUI;
2. enviar prompt curto;
3. confirmar streaming;
4. verificar `qwen-omlx status`;
5. confirmar que logs não mostram API key nem prompt em nível indevido;
6. testar uma resposta longa.

### 8.5 Validar a janela de contexto

Os gates e números desta subseção foram executados no perfil uncensored implantado `qwen38-omlx`. Eles são evidência histórica desse processo, não validação empírica do checkpoint `fcmeyer`; o guia novo exige canário próprio.

A validação de `262144` deve separar cinco gates:

1. **metadados nativos:** `config.json:text_config.max_position_embeddings` e `tokenizer_config.json:model_max_length` iguais a `262144`;
2. **runtime efetivo:** `/v1/models` anuncia `max_model_len=262144` e `/v1/models/status` mostra `model_context_length=max_context_window=262144`;
3. **aceitação acima do limite antigo:** uma inferência real com mais de `32768` prompt tokens gera saída e retorna métricas de uso;
4. **canário profundo:** um prompt próximo do threshold operacional confirma prefill, memória e streaming sem ultrapassar a janela total;
5. **fronteira após promoção:** os quatro modos HTTP reais chegam exatamente ao total `262144` sem ultrapassagem especulativa, vazamento de escopo ou abort de memória.

O gate 3 foi executado depois do restart com `40012` prompt tokens, 4 tokens de saída, streaming, `finish_reason=length` e contagem idêntica entre tokenizer e servidor. O prefill mediu `175,83 prompt tok/s` e o TTFT foi `227,56 s`; isso prova capacidade acima de 32K e também evidencia o custo de contexto real.

O gate 4 também passou: `245760` prompt tokens, 1 token de saída, streaming, `finish_reason=length`, `96,08 prompt tok/s`, TTFT de `2557,78 s` e parede de `2558,19 s` (~42m38s), sem abort do memory guard e com serviço saudável ao final. Esse canário reaproveitou `38912` tokens e reprocessou `206848`; portanto, prova capacidade próxima ao threshold nesse estado medido, não um prefill totalmente frio nem qualidade de longo contexto.

Após revisão independente e promoção dos guards de escopo da requisição e de fronteira do Lightning MTP, um quinto gate cobriu os quatro modos HTTP reais no processo novo:

| Endpoint/modo | Prompt + saída efetiva | Parede | Prefixo em cache |
|---|---:|---:|---:|
| Chat streaming | `262140 + 4` | `71,301 s` | `258048` |
| Chat não streaming | `262143 + 1` | `36,497 s` | `260096` |
| Completion raw streaming | `262140 + 4` | `36,467 s` | `260096` |
| Completion raw não streaming | `262143 + 1` | `36,126 s` | `260096` |

Todos terminaram exatamente em `262144` tokens, com `finish_reason=length`; cada chamada pediu `8192` tokens, e a fachada vinculou à requisição apenas `4` ou `1` token restante. Esse gate prova segurança da fronteira ao vivo — não prefill frio. Não houve `_MtpSafetyViolation` nem abort do memory guard. O maior RSS pontual observado durante a campanha foi ~`30,52 GiB`, a menor memória livre sistêmica foi `33%`, e não houve trace contínuo de pico.

O verificador de inicialização complementa os canários com matriz ASGI nos quatro modos completion/chat × streaming/não streaming, concorrência/erro, perfil isolado de rollback `32768`, limites MTP de borda e comparação byte a byte dos fontes críticos instalados com o wheel fixado. Depois dos canários, tanto o verificador rápido quanto o criptográfico completo passaram; um smoke autenticado pelo proxy do Open WebUI também retornou HTTP 200 pelo modelo `local.qwen38-omlx`. A evidência estruturada, incluindo hashes do código promovido, está em `~/models/qwen38-omlx/context-256k-validation.json`.

Não use apenas o valor exibido pelo frontend como evidência. Contexto profundo tem custo real: com concorrência `1`, uma requisição longa ocupa o modelo durante o prefill. Para as 16 camadas de atenção completa, o KV residente cresce aproximadamente `64 KiB` por token em BF16 — cerca de `4 GiB` em `65536` tokens e `16 GiB` em `262144` — além dos pesos, do estado recorrente e dos transientes. A primagem MTP pode acrescentar aproximadamente `4 KiB` por token, perto de `1 GiB` no teto. O log de inicialização que estima `16 MiB` por bloco de 64 tokens usa todas as 64 camadas como estimativa conservadora de bloco e não deve ser multiplicado como KV residente do híbrido. A diferença de `16384` no threshold é margem nominal: `8192` podem ser usados pela saída e o restante absorve, de forma não garantida, system prompt, Tools e erro de estimativa. Schemas adicionados depois da decisão de compactação podem consumir essa margem, reduzir a saída efetiva ou causar rejeição pelo guard total; eles não antecipam automaticamente a compactação.

---

## 9. Open Terminal dedicado por usuário

O terminal integrado foi implantado com um container **Open Terminal `0.12.1` por conta aprovada**. Todos continuam usando somente `https://chat.seudominio.com`; ao selecionar o ícone de terminal, o Open WebUI abre uma sessão no container já existente daquele usuário.

```text
chat.seudominio.com
  ├── usuário A → proxy autenticado → container A → ~/AI-Workspace/a
  ├── usuário B → proxy autenticado → container B → ~/AI-Workspace/b
  └── usuário C → proxy autenticado → container C → ~/AI-Workspace/c
```

Não é criado um container a cada clique. O container é provisionado uma vez; cada uso cria ou retoma uma sessão dentro dele. Os containers usam:

- imagem oficial fixada por digest;
- porta aleatória do intervalo `3101–3199`, publicada somente em `127.0.0.1`;
- rede Docker dedicada com um único container;
- 3 CPUs, 8 GiB de RAM e limite de 256 processos;
- `no-new-privileges` e todas as capabilities removidas;
- nenhum Docker socket, `$HOME`, `~/.ssh`, Keychain ou diretório de outro usuário;
- uma API key individual em arquivo `0600`, ausente de `argv`, metadata e logs;
- bind mount único de `~/AI-Workspace/<slug>` para `/workspace`.

As respostas do proxy recebem CSP com `sandbox allow-scripts`, sem `allow-same-origin`, para reduzir acesso de HTML gerado pelo terminal ao origin do Open WebUI.

### 9.1 Onboarding de novo usuário

Criar uma conta do Open WebUI não provisiona automaticamente um container. O processo deliberadamente exige uma ação administrativa:

1. criar ou aprovar a conta em `chat.seudominio.com`;
2. manter `role=user`, salvo quando administração plena for realmente necessária;
3. executar:

```bash
~/services/open-webui-terminals/provision-user.sh
```

O comando lista contas com e-mails mascarados e pergunta o usuário e o slug. Para automação explícita:

```bash
~/services/open-webui-terminals/provision-user.sh \
  --user '<EMAIL_EXATO_OU_UUID>' \
  --slug '<identificador-curto>'
```

Ele é idempotente e executa estes gates antes de concluir:

- health do container;
- `/execute` sem chave retorna `401`;
- `pwd` autenticado termina com código zero em `/workspace`;
- conexão é registrada pela API administrativa suportada;
- usuário atribuído enxerga o terminal;
- outros usuários comuns não o enxergam;
- key não aparece em Docker metadata, logs ou process snapshot.

Depois, o usuário deve sair e entrar novamente ou fazer hard refresh. O terminal pessoal aparecerá no seletor sob **System**.

Inventário operacional:

```bash
~/services/open-webui-terminals/provision-user.sh --list
docker ps --filter 'name=openwebui-terminal-'
```

O estado owner-only fica em `~/services/open-webui-terminals/state.json`; keys ficam sob `secrets/<slug>/api-key`. Ambos já entram no backup cifrado do control plane. As pastas `~/AI-Workspace/<slug>` não entram nesse archive e exigem backup próprio. **Ainda não existe um comando de deprovisionamento:** não remova container, conexão ou workspace manualmente sem um procedimento que preserve os arquivos do usuário.

### 9.2 Limite da ACL administrativa

Usuários comuns veem somente o terminal concedido ao próprio UUID. Um usuário `admin` é root-equivalente no Open WebUI e pode ver/reconfigurar todas as integrações por design; ACL não é uma fronteira contra o operador da instância. Use `role=user` para quem não precisa administrar o serviço.

### 9.3 Navegador visual e autenticação

Open Terminal fornece shell, arquivos, Git e tools. Para Chromium visual, login manual, MFA ou CAPTCHA, não compartilhe perfis autenticados nem monte o perfil Chrome do macOS.

Depois da implantação inicial do Computer, foi adicionado um **POC universal HITL multiusuário** separado, documentado em [`04-browser-hitl-multiusuario-poc.md`](04-browser-hitl-multiusuario-poc.md). Ele mantém perfis persistentes isolados para admin e user-a, vincula ownership ao UUID do Open WebUI e impõe lock server-side entre agente e humano. O broker já está publicado em `browser.seudominio.com` atrás de Cloudflare Access com One-Time PIN exclusivamente nesse hostname; o E2E móvel de baixo risco ainda está pendente, e contas de alto valor continuam fora do escopo aprovado. `chat.seudominio.com` permanece sem Access/OTP, protegido apenas pelo login do Open WebUI.

O Computer não é necessário para quem usa apenas chat e terminal.

O perfil híbrido implantado mantém Computer ativo somente para admin. user-a e user-b têm containers opcionais parados, sem auto-restart; user-c e user-d não têm Computer. O ambiente ativo usa:

- interface local `http://renato.localhost:3011`, publicada somente em `127.0.0.1:3011`;
- modelo privado `cptr/admin` no `chat.seudominio.com`, com grant de leitura somente ao UUID de admin;
- workspace `/workspaces/renato` sobre a mesma pasta Mac usada pelo Open Terminal;
- Chromium gerenciado e persistente em `/data/chromium-renato`, nunca o perfil Chrome do macOS;
- Xvfb sem listener TCP, Chromium sandbox ativo, seccomp default-deny, zero capabilities e `no-new-privileges`;
- password manager, autofill, Browser Sign-in e Sync desabilitados por policy;
- Qwen cadastrado no Computer com key cifrada e gateway key armazenada somente como hash dentro do Computer;
- log operacional em `WARNING` para não registrar tokens efêmeros do encoder e audit log separado em `METADATA`.

A imagem local deriva do digest oficial Computer `0.9.21` e inclui um patch versionado/fail-closed de duas chamadas para que abas visuais managed usem o mesmo CDP persistente das browser tools. Isso permite takeover manual e automação compartilharem cookies sem usar o modo personal Chrome.

O Computer **não está publicado remotamente**. `browser.seudominio.com` publica somente o broker Browser HITL endurecido, não a porta `3011` nem a interface do Computer. Para acesso futuro ao Computer fora do Mac, configure Tailscale ou outro hostname Access separado; nunca publique a porta `3011` somente com a senha local.

---

## 10. OpenRouter opcional

É possível adicionar OpenRouter mesmo sem VPS:

```text
URL:       https://openrouter.ai/api/v1
API Key:   key dedicada com limite de gasto
Prefix ID: openrouter
```

Use **Model IDs (Filter)** para uma pequena allowlist. Revise retenção, logging e treinamento de cada provedor selecionado.

Limitação incontornável: com o Mac desligado, o Open WebUI também desliga e o OpenRouter não fica acessível por essa interface.

---

## 11. Autenticação pública escolhida

A implantação começou com Cloudflare Access + One-time PIN e o login interno do Open WebUI. Após o primeiro teste, o proprietário optou por remover o OTP e manter somente o login nativo.

Estado final:

- não existe Access application para `chat.seudominio.com`;
- não existe validação `originRequest.access` no Tunnel;
- a tela de login do Open WebUI é publicamente alcançável;
- signup está desabilitado tanto na configuração efetiva quanto na persistida;
- existem cinco contas internas conhecidas: um admin e quatro contas comuns;
- o modelo `local.qwen38-omlx` é público para usuários autenticados e foi validado com inferência SSE usando conta comum;
- o modelo agentic `cptr/admin` é visível e invocável somente por admin entre as contas atuais;
- a senha aleatória de 48 caracteres do admin teve a política de complexidade validada sem exposição do valor;
- cookie é `Secure`, `HttpOnly` e `SameSite=Strict`;
- login incorreto não vaza detalhes internos;
- rate limit Cloudflare bloqueia após cinco `POST /api/v1/auths/signin` por IP em 10 segundos, durante 10 segundos.

Essa escolha reduz a defesa em profundidade em troca de UX. Para restaurar MFA/OTP futuramente, recrie uma Access application de e-mail exato antes de reativar `originRequest.access` com AUD correspondente.

---

## 12. Criar o Tunnel no Mac

### 12.1 Estado DNS

Confirme no dashboard:

```text
Websites → seudominio.com → Overview → Status: Active
SSL/TLS → Universal SSL: Active
```

Não crie `A`/`AAAA` para o IP residencial. A Published application route gerencia o DNS proxied de `chat.seudominio.com`. Resolva qualquer registro conflitante antes.

### 12.2 Criar Tunnel remoto

```text
Networking → Tunnels → Create tunnel
Nome: openwebui-mac
Tipo: cloudflared
Sistema: macOS arm64
```

Não execute um comando com token literal. Grave o token diretamente em arquivo owner-only e limpe o clipboard:

```text
~/.config/cloudflared-openwebui/tunnel.token   modo 0600
```

Use `cloudflared >= 2025.4.0` com `--token-file`.

### 12.3 LaunchAgent do Tunnel

Arquivo implantado:

```text
~/Library/LaunchAgents/com.local.cloudflared-openwebui.plist
```

`ProgramArguments` implantado:

```xml
<array>
  <string>/opt/homebrew/bin/cloudflared</string>
  <string>tunnel</string>
  <string>--config</string>
  <string>/Users/SEU_USUARIO/.config/cloudflared-openwebui/config.yml</string>
  <string>--no-autoupdate</string>
  <string>--metrics</string>
  <string>127.0.0.1:20241</string>
  <string>--loglevel</string>
  <string>info</string>
  <string>run</string>
  <string>--token-file</string>
  <string>/Users/SEU_USUARIO/.config/cloudflared-openwebui/tunnel.token</string>
</array>
```

Use o caminho de `command -v cloudflared`; não presuma Homebrew ou arquitetura. O LaunchAgent inicia apenas após login. Não habilite login automático somente para isso.

Mantenha log em `info`; debug pode registrar headers e informações sensíveis.

### 12.4 Published application route

No Tunnel `openwebui-mac`:

```text
Route type:  Published application
Hostname:    chat.seudominio.com
Service URL: http://127.0.0.1:3000
```

A configuração remota contém somente essa regra e um catch-all `http_status:404`. Por decisão do proprietário, **Protect with Access está desabilitado**; a autenticação ocorre no Open WebUI. Não crie route para `127.0.0.1:8084`.

---

## 13. Auto-start do Open WebUI, Tunnel e Qwen

A implantação ativa usa três LaunchAgents de usuário:

| Label | Processo | Política |
|---|---|---|
| `com.local.openwebui` | Open WebUI | `RunAtLoad` + `KeepAlive` |
| `com.local.cloudflared-openwebui` | Cloudflare Tunnel | `RunAtLoad` + `KeepAlive` |
| `com.local.qwen-omlx` | Qwen/oMLX | `RunAtLoad`; o processo fica em foreground sob o `launchd` |

Eles iniciam quando o proprietário faz login no macOS; não transformam o Mac em serviço disponível antes do login. Os três plists passaram por `plutil -lint`, e uma reinicialização controlada da sessão `launchd` provou recuperação conjunta seguida de uma completion pública. Não foi feito reboot físico do Mac.

Arquivo do WebUI:

```text
~/Library/LaunchAgents/com.local.openwebui.plist
```

Estrutura essencial:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.local.openwebui</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/SEU_USUARIO/services/open-webui-mac/app/start-open-webui.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/SEU_USUARIO/services/open-webui-mac</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/SEU_USUARIO/services/open-webui-mac/logs/stdout.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/SEU_USUARIO/services/open-webui-mac/logs/stderr.log</string>
</dict>
</plist>
```

Substitua todos os placeholders. Valide antes de carregar:

```bash
plutil -lint ~/Library/LaunchAgents/com.local.openwebui.plist
```

Use `launchctl bootstrap gui/$(id -u) ...`/`bootout` conforme a versão do macOS. Não use `sudo`: MLX/Metal e os arquivos privados pertencem ao usuário.

O Qwen foi deliberadamente incluído no auto-start. O launcher `start-qwen-omlx.sh` mantém compatibilidade com o PID file do controlador existente, recusa substituir PID alheio e nunca altera o bind de `127.0.0.1:8084`.

### 13.1 Ordem de startup

Os três LaunchAgents são independentes; não há garantia de que o Qwen já esteja pronto quando o WebUI abrir. Isso é aceitável: o WebUI e o Tunnel sobem sem o modelo, e a conexão local fica disponível assim que o Qwen termina de carregar. A validação deve aguardar os health checks antes de testar chat. Não crie loop infinito de restart nem passe segredos em argumentos.

---

## 14. Testes de aceitação

### 14.1 Local

```bash
curl --fail http://127.0.0.1:3000/health
lsof -nP -iTCP:3000 -sTCP:LISTEN
lsof -nP -iTCP:8084 -sTCP:LISTEN
```

Esperado:

```text
Open WebUI → 127.0.0.1:3000
qwen-omlx → 127.0.0.1:8084
```

Falhar se aparecer `*:3000`, `0.0.0.0:3000`, `*:8084` ou `0.0.0.0:8084`.

Resultado final de 25/08/2026:

- WebUI em `127.0.0.1:3000`;
- Qwen em `127.0.0.1:8084`;
- métricas do Tunnel em `127.0.0.1:20241`;
- `qwen-omlx verify --quick` e `pip check` passaram;
- nenhuma key, senha, token ou secret implantado foi encontrado nos logs.

### 14.2 Celular

Com 4G/5G, fora do Wi-Fi:

1. abrir `https://chat.seudominio.com`;
2. confirmar que a tela é diretamente o login Open WebUI, sem OTP;
3. fazer login com `<EMAIL_ADMIN>` e a senha do password manager;
4. conversar com o Qwen;
5. confirmar streaming;
6. abrir aba anônima e verificar que o login reaparece;
7. confirmar que signup não é oferecido.

O gate automatizado público final autenticou o admin por HTTPS, recebeu cookie `Secure`, `HttpOnly` e `SameSite=Strict`, descobriu `local.qwen38-omlx`, recebeu mais de um evento SSE com o conteúdo esperado e o terminador `[DONE]`. Sem autenticação, a API de usuários respondeu `401`. Uma segunda execução usando a conta comum confirmou visibilidade e inferência do modelo público.

As rotas públicas `/signup`, `/docs`, `/openapi.json` e `/redoc` retornam o shell HTML da SPA em `v0.11.0`; não expõem formulário de cadastro nem especificação OpenAPI. Um bloqueio adicional no edge seria apenas redução opcional de ruído de scanners, não correção de uma API documental exposta.

### 14.3 Negativos

- parar `qwen-omlx`: WebUI abre, modelo local falha de modo controlado;
- parar Open WebUI: `chat.seudominio.com` retorna origem indisponível;
- parar Tunnel: WebUI continua local, hostname público falha;
- desligar internet: processos WebUI/Qwen continuam locais, mas o login HTTP exige o procedimento controlado dos cookie flags ou HTTPS local; acesso público e OpenRouter falham;
- desligar Mac: tudo deste cenário fica offline.

---

## 15. Hardening obrigatório

### Open WebUI

- bind somente em `127.0.0.1:3000`;
- autenticação nativa habilitada;
- signup fechado após o admin;
- JWT curto; sem Redis, logout não revoga imediatamente token emitido;
- cookies Secure para o hostname HTTPS;
- CORS somente `https://chat.seudominio.com`;
- runtime de plugins habilitado somente para a Tool Python Browser HITL revisada; criação/importação/exportação por usuários comuns e instalação automática via pip permanecem desabilitadas; execução de código genérica permanece desabilitada;
- passthrough e direct connections desabilitados;
- web search, automations e subagents desabilitados até revisão;
- uploads limitados; allowlist sem ponto (`pdf,txt,md,docx,csv`) validada com `.txt → 200` e `.exe → 400`;
- audit log `METADATA`, nunca bodies por padrão;
- venv e versão fixos;
- arquivos/diretórios owner-only.

### Cloudflare

| Controle | Estado |
|---|---|
| CNAME proxied até o Tunnel, sem IP residencial | validado por API |
| `chat.seudominio.com`: login Open WebUI público, sem Access/OTP | validado por API e HTTPS |
| Rate limit de login: 5 requests/IP/10 s, bloqueio 10 s | validado com `429` |
| Tunnel Token em arquivo, não em `argv` | validado |
| Métricas somente em `127.0.0.1:20241` | validado |
| Catch-all remoto `http_status:404` | validado por API |
| Managed Free Ruleset/DDoS L7 | cobertura padrão esperada; configuração específica não inventariada |
| Alerta quando Tunnel estiver offline | pendente de confirmação |
| Ausência de port forwarding no roteador | pendente de verificação no roteador |

A regra normativa continua sendo: não abra nenhuma porta inbound no roteador.

### Qwen

- `127.0.0.1:8084` e Bearer obrigatórios;
- fachada mínima atual;
- egress sandbox mantido;
- sem MCP, web, remote code, tools ou model mutation;
- concorrência 1;
- janela nativa/efetiva/anunciada em `262144` tokens e saída máxima em `8192`;
- memory guard `safe` permanece habilitado; não elevar `iogpu.wired_limit_mb` apenas para perseguir contexto sem medir pressão real;
- cache SSD limitado a `40GB` e sem hot cache reservado;
- `qwen-stable` preservado;
- não publicar a API no Tunnel.

### Modelo uncensored implantado

Este aviso se refere especificamente ao perfil atual `qwen38-omlx`/`pyros-vault`, não ao checkpoint `fcmeyer` recomendado para instalações novas. O modelo implantado é refusal-removed. Não ofereça acesso anônimo nem conecte-o automaticamente a shell, arquivos, rede, e-mail, SSH ou cloud. Saídas são não confiáveis e não devem ser executadas sem validação humana.

---

## 16. Backup e restore local

`data/` contém banco, chats, uploads, configurações e credenciais de conexão recuperáveis. Todo backup deve ser cifrado.

Na implantação, `app/backup-open-webui.sh` cria um snapshot online consistente com `sqlite3 .backup`, empacota dados, secrets necessários, launchers, plists e metadados de recuperação e cifra o resultado com `age`. Ele usa `set -euo pipefail`, grava primeiro em `.partial`, valida tar e SQLite antes do `mv` final e exclui deliberadamente `secrets/admin-password`.

O backup geral mais recente, `open-webui-mac-20260827-060049.tar.gz.age`, teve checksum, descriptografia isolada, leitura do tar e `PRAGMA integrity_check` validados. Além dos cinco usuários, provisionador/estado, quatro keys de terminal, artefatos/patches e gateway key do Computer, ele inclui o control plane do Qwen, configurações/secrets owner-only, wheel oMLX fixado, metadados mínimos do checkpoint, `context-256k-validation.json` e a matriz bruta durável `context-256k-boundary-live-results.json`. Exclui deliberadamente os shards de 17 GB, o venv reconstruível, logs e cache SSD de 40 GB; o restore do modelo exige reconstrução pelas identidades fixadas e `qwen-omlx verify`. Nenhuma pasta `AI-Workspace`, volume Chromium ou senha bootstrap entra no backup geral. O volume separado do Computer, incluindo banco, hash da senha, chats e perfil Chromium, está no backup cifrado `computer-renato-data-20260826-114648.tar.gz.age`, também validado por restore isolado e integridade SQLite. Backups anteriores permanecem intactos e os três primeiros backups gerais podem conter a senha bootstrap.

A identidade está em `~/.config/open-webui-backup/identity.txt` (`0600`). **Ainda não existe cópia de desastre independente:** copie o arquivo `.age` para um destino externo e guarde a identidade privada em destino separado do backup cifrado. Não coloque os dois na mesma mídia ou conta; alternativamente, proteja a identidade com criptografia/passphrase adicional e guarde a passphrase separadamente. Em 25/08/2026, somente `disk0` estava disponível: o volume Time Machine `/Volumes/TimeMachine` pertence ao mesmo disco físico interno e não protege contra falha desse SSD.

A fonte operacional autoritativa é:

```bash
~/services/open-webui-mac/app/backup-open-webui.sh
```

Não substitua o script por um pipeline ad hoc sem `pipefail`, arquivo parcial, validação da descriptografia e `PRAGMA integrity_check`. Para validar a cópia de desastre, use a identidade guardada separadamente para descriptografar uma **cópia externa** em diretório temporário e confirme tar + SQLite sem sobrescrever o estado ativo.

Política-alvo ainda não automatizada:

- diário e antes de upgrades;
- 7 diários, 4 semanais e 6 mensais;
- RPO pretendido de 24 h, ainda não atingido por agendamento monitorado;
- restore trimestral em diretório/usuário separado;
- nunca sobrescrever o estado falho antes de diagnosticar.

Restore:

1. parar Open WebUI;
2. verificar checksum;
3. extrair em diretório novo, não sobre o original;
4. restaurar venv/versão, `data`, `secrets` e `env` compatíveis;
5. iniciar manualmente em outra porta loopback;
6. validar login, histórico, Qwen e OpenRouter;
7. somente então promover o restore.

Migrações de banco podem impedir downgrade apenas do pacote; restaure pacote e dados do mesmo ponto.

---

## 17. Atualização e rollback

Antes de atualizar:

1. revisar release notes;
2. gerar e validar backup cifrado;
3. clonar o venv atual ou criar novo venv ao lado;
4. instalar a nova versão no novo ambiente;
5. iniciar em porta loopback temporária;
6. validar migrações e funções essenciais;
7. trocar o LaunchAgent somente após aprovação;
8. preservar venv e backup anteriores durante a retenção.

Rollback real pode exigir restaurar o banco anterior, não apenas reativar o venv antigo.

### Rollback específico da janela de 256K

Se prompts profundos causarem pressão de memória ou latência operacional inaceitável, reverta de forma consistente — não altere somente o número mostrado no WebUI:

1. em `~/models/qwen38-omlx/state/settings.json`, restaurar `sampling.max_context_window` e `sampling.max_context_window_policy` para `32768`;
2. em `state/model_settings.json`, restaurar `models.qwen38-omlx.max_context_window` para `32768`; o verificador aceita somente o par coerente de rollback `32768` ou o nativo `262144`, enquanto checkpoint/tokenizer permanecem fixos em `262144`;
3. em `~/services/open-webui-mac/env`, restaurar threshold/cap para `24000`;
4. pela configuração persistida do Open WebUI, restaurar threshold/cap globais e `compact_token_threshold` do workspace model para `24000`;
5. executar `qwen-omlx verify --quick`; o banner do launcher lê o cap efetivo do JSON, sem número hardcoded;
6. reiniciar primeiro `com.local.qwen-omlx`, depois `com.local.openwebui`;
7. exigir `/v1/models:max_model_len=32768`, health saudável e um chat curto antes de encerrar o rollback.

O cache SSD pode continuar em `40GB`; reduzi-lo de volta para `20GB` é opcional e não exige apagar arquivos manualmente. Não use `rm -rf` no cache durante rollback; o gerenciador aplica o teto e a limpeza compatível.

Para remover o acesso remoto sem apagar nada local:

1. remover/desabilitar a route `chat.seudominio.com`;
2. revogar o Tunnel Token;
3. parar o LaunchAgent `cloudflared`;
4. manter Open WebUI e Qwen no loopback.

---

## 18. Checklist de go-live

### Instalação local

- [x] Python é 3.12.14, não 3.13+;
- [x] Open WebUI está em venv separado do oMLX;
- [x] versão, freeze e checksum do freeze estão registrados;
- [x] `DATA_DIR` é explícito e owner-only;
- [x] WebUI secret está em arquivo `0600`;
- [x] primeiro admin foi criado localmente;
- [x] signup está fechado na configuração efetiva e persistida;
- [x] cookies foram alterados para Secure antes da publicação;
- [x] listener do WebUI é somente `127.0.0.1:3000`.

### Qwen

- [x] `qwen-omlx verify --quick` passa;
- [x] listener é somente `127.0.0.1:8084`;
- [x] conexão do WebUI usa `http://127.0.0.1:8084/v1`;
- [x] Bearer key está configurada e foi testada sem aparecer em `argv`/logs;
- [x] checkpoint, tokenizer, runtime e endpoint convergem em `262144` tokens;
- [x] facade limita saída a `8192`, rejeita prompt sem espaço, vincula o teto à requisição antes do streaming e garante `prompt + saída <= 262144` em testes HTTP reais;
- [x] MTP reduz drafts junto ao teto e aplica guard pelos offsets reais dos caches alvo/cabeça, cobrindo forwards especulativos além dos tokens emitidos;
- [x] canários reais passaram em `40012`, `245760` e `260000` prompt tokens, com limitações registradas no artefato de evidência;
- [x] após a promoção dos guards finais, chat/completion raw × streaming/não streaming fecharam exatamente em `262140 + 4` e `262143 + 1 = 262144`, sem violação MTP ou abort de memória;
- [x] Open WebUI persiste threshold/cap e workspace model em `245760` após restart e o proxy autenticado continuou gerando pelo processo promovido;
- [x] rollback coerente em `32768` passou no verificador usando clone temporário isolado;
- [x] verificação criptográfica completa do wheel, quatro shards e 12 metadados passou;
- [x] não existe `llm-home.seudominio.com` nem route para 8084;
- [x] streaming funciona publicamente de ponta a ponta.

### Open Terminal

- [x] quatro contas aprovadas têm container, rede, key e workspace próprios;
- [ ] a quinta conta atual ainda não foi provisionada no Open Terminal;
- [x] usuários comuns veem somente o terminal atribuído ao próprio UUID;
- [x] portas `3101–3104` usam somente loopback;
- [x] `/execute` sem key retorna `401` e `pwd` autenticado retorna `/workspace`;
- [x] Qwen chamou `run_command`; o log do terminal registrou exatamente `pwd`;
- [x] CSP do proxy usa sandbox sem `allow-same-origin`;
- [x] Docker Desktop inicia no login e containers usam `restart=unless-stopped`;
- [x] estado e keys entram no backup cifrado do control plane;
- [ ] pastas `~/AI-Workspace/*` ainda precisam de política de backup própria;
- [x] Computer visual foi inicializado somente para admin e permanece em loopback;
- [x] `cptr/admin` é privado por UUID e usuários comuns recebem modelo indisponível ao tentar invocá-lo;
- [x] Qwen executou exatamente `pwd` no Computer e `browser_navigate` abriu `example.com`;
- [x] takeover visual, Chromium/CDP, sandbox, restart e backups cifrados foram validados;
- [x] POC Browser HITL local foi validado com perfis isolados para admin/user-a, lock `423`, same-session noVNC e retomada por nova epoch;
- [x] POC Browser HITL publicado separadamente em `browser.seudominio.com`, com Access somente OTP, JWT/e-mail vinculados e chat sem OTP; ainda falta o E2E móvel de baixo risco antes de contas principais;
- [ ] acesso remoto do Computer ainda não foi publicado; exige Tailscale ou Cloudflare Access.

### Cloudflare

- [x] `chat.seudominio.com` permanece sem Access/OTP conforme decisão do proprietário;
- [x] `browser.seudominio.com` usa Access/OTP separado e não altera o login do chat;
- [x] login público do chat usa somente autenticação nativa do Open WebUI;
- [x] rate limit do endpoint de login foi criado e testado com `429`;
- [x] Tunnel Token usa `--token-file`;
- [x] `chat.seudominio.com` aponta pelo Tunnel, sem A/AAAA residencial;
- [x] login HTTPS e chat público funcionam;
- [x] senha errada e signup público são negados.

### Operação

- [x] os três LaunchAgents recuperaram os serviços numa reinicialização controlada da sessão `launchd`;
- [ ] recuperação automática após reboot físico e novo login ainda não foi comprovada;
- [ ] o teste negativo isolado do Tunnel ainda não foi repetido; o origin local é independente por construção e está saudável;
- [x] a varredura de 25/08/2026 nos logs dos três LaunchAgents não encontrou os valores secretos implantados nem os marcadores dos prompts de teste;
- [x] backup cifrado, descriptografia em diretório temporário e integridade SQLite foram testados;
- [x] backup endurecido exclui `secrets/admin-password`;
- [ ] backup `.age` e identidade privada ainda precisam de cópias externas em destinos separados;
- [ ] backups antigos contendo potencialmente a senha bootstrap ainda exigem decisão de retenção/remoção e rotação;
- [ ] agendamento, retenção 7/4/6 e alerta de falha do backup ainda não estão automatizados;
- [ ] restore trimestral completo a partir das futuras cópias externas ainda não foi executado;
- [ ] alerta de saúde do Tunnel ainda não foi confirmado;
- [x] WebUI, Qwen e métricas do Tunnel usam somente loopback, nunca `0.0.0.0`;
- [ ] ausência de port forwarding ainda precisa ser confirmada no roteador.

---

## 19. Sequência recomendada

1. criar diretórios e venv privado;
2. instalar versão fixa do Open WebUI;
3. criar configuração e secret;
4. iniciar em `127.0.0.1:3000`;
5. criar admin e fechar signup;
6. validar Qwen pelo loopback;
7. adicionar OpenRouter opcional;
8. ativar cookies Secure;
9. criar Tunnel com token-file;
10. publicar somente `chat.seudominio.com → 127.0.0.1:3000`;
11. criar rate limit específico do login;
12. validar HTTPS, login, signup negado e SSE público;
13. criar LaunchAgents;
14. instalar/iniciar Docker Desktop;
15. provisionar um Open Terminal por usuário aprovado;
16. validar ACL, CSP e tool call do Qwen;
17. configurar backup e monitoramento.

Cloudflare Access foi removido de `chat.seudominio.com` por opção do proprietário e continua ausente do chat. Posteriormente, uma aplicação separada, restrita a One-Time PIN, foi criada exclusivamente para `browser.seudominio.com`; ela não altera a autenticação do Open WebUI.

---

## 20. Referências oficiais

### Open WebUI

- Quick Start: <https://docs.openwebui.com/getting-started/quick-start/>
- OpenAI-compatible providers: <https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/>
- Hardening: <https://docs.openwebui.com/getting-started/advanced-topics/hardening/>
- Environment variables: <https://docs.openwebui.com/reference/env-configuration/>
- Updating: <https://docs.openwebui.com/getting-started/updating/>
- Releases: <https://github.com/open-webui/open-webui/releases>

### Cloudflare

- Create remotely managed Tunnel: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/>
- Rate limiting rules: <https://developers.cloudflare.com/waf/rate-limiting-rules/create-api/>
- Tunnel token-file/run parameters: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/>
- macOS service: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/macos/>

### OpenRouter

- Authentication: <https://openrouter.ai/docs/api/reference/authentication>

---

## 21. Conclusão

Sem VPS, a arquitetura é mais simples: WebUI, histórico e inferência ficam no Mac; somente a interface atravessa o Cloudflare Tunnel. A API `qwen-omlx` nunca ganha hostname público e continua protegida por loopback e Bearer. Nesta implantação, a tela de login do WebUI é pública por decisão explícita, com senha forte, signup fechado e rate limiting Cloudflare; não há OTP/MFA no edge.

O custo dessa simplicidade é disponibilidade: desligar o Mac remove WebUI, Qwen e o acesso ao OpenRouter por essa interface. Essa não é uma falha de configuração; é a propriedade central do cenário sem VPS.
