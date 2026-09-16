# Open WebUI com VPS: cloud contínua, OpenRouter e Qwen no Mac

> [English](../../docs/03-deploy-with-vps.md) · **Português**

**Status:** runbook de implantação; nenhuma instalação foi executada  
**Data de referência:** 27 de agosto de 2026  
**Versões de referência verificadas:** Open WebUI `v0.11.0`; `cloudflared` `2026.8.2`  
**Objetivo:** manter o Open WebUI e o OpenRouter disponíveis quando o Mac estiver desligado, usando `qwen38-official-omlx` remotamente somente quando o Mac estiver online  
**Domínios:** `chat.seudominio.com` para a interface e `llm-home.seudominio.com` para a API doméstica protegida

> Este é exclusivamente o cenário **com VPS**. Para executar tudo no Mac, sem VPS, use [`02-deploy-macos-cloudflare-tunnel.md`](02-deploy-macos-cloudflare-tunnel.md).
>
> Como este cenário ainda não foi executado, ele adota para instalações novas o perfil clean-room [`../examples/qwen38-official-omlx/README.md`](../../examples/qwen38-official-omlx/README.md): checkpoint comunitário `fcmeyer/...@0299356…`, declarado como derivado do `Qwen/Qwen3.8-27B`. Instale, verifique e execute o canário 40K do modelo no Mac antes de publicar a API pelo Tunnel.

---

## 1. Garantia arquitetural

> **Cloudflare Tunnel não hospeda o Open WebUI.** A continuidade vem da VPS, onde o processo e seus dados permanecem ativos.

```text
                         ┌────────────────────────────→ OpenRouter
Celular → Cloudflare → Open WebUI em VPS/cloud
                         └→ Cloudflare Access/Tunnel → qwen38-official no Mac
```

Se o Mac desligar:

- Open WebUI continua online;
- histórico, login e configurações continuam online;
- OpenRouter e outros provedores remotos continuam funcionando;
- somente `qwen38-official-omlx` fica indisponível;
- quando Mac, modelo e túnel voltarem, o modelo local volta sem migrar pesos para a cloud.

Se a VPS desligar, a interface fica indisponível, embora o Qwen continue utilizável diretamente no Mac. Não há fallback silencioso do Qwen para OpenRouter.

---

## 2. Arquitetura

Serão usados dois túneis independentes e dois hostnames:

```text
                                Internet
                                   │
                         https://chat.seudominio.com
                                   │
                    Cloudflare Access — login humano
                                   │
                     Tunnel 1: openwebui-cloud
                                   │
                         Open WebUI na VPS
                         /                 \
                        /                   \
        https://openrouter.ai/api/v1        https://llm-home.seudominio.com/v1
                                                     │
                                      Cloudflare Access — Service Auth
                                                     │
                                          Tunnel 2: qwen-home
                                                     │
                                     qwen38-official 127.0.0.1:8084
                                             no M3 Max
```

### 2.1 Responsabilidade de cada camada

| Componente | Onde roda | Responsabilidade |
|---|---|---|
| Open WebUI | VPS/cloud | interface, usuários, histórico e roteamento para provedores |
| Cloudflare Access do chat | edge Cloudflare | autenticação humana antes do Open WebUI |
| Cloudflare Tunnel do chat | VPS/cloud | publica o WebUI sem abrir porta pública no servidor |
| OpenRouter | serviço remoto | modelos cloud disponíveis mesmo com o Mac offline |
| Cloudflare Access da API local | edge Cloudflare | autenticação máquina-a-máquina com Service Token |
| Cloudflare Tunnel da API local | Mac | encaminha apenas o endpoint Qwen para o Open WebUI cloud |
| `qwen38-official` | Mac | inferência local em `127.0.0.1:8084` |

### 2.2 Dupla autenticação do endpoint local

Cada request da VPS ao Qwen terá duas credenciais independentes:

```text
CF-Access-Client-Id / CF-Access-Client-Secret
    → autoriza a VPS no Cloudflare Access

Authorization: Bearer <QWEN_API_KEY>
    → autoriza a inferência no próprio qwen38-official
```

O Open WebUI `v0.11.0` suporta API key Bearer e headers customizados por conexão OpenAI-compatible. O backend dessa versão primeiro cria `Authorization: Bearer <API key>` e depois acrescenta o mapa de headers customizados; portanto, os dois mecanismos coexistem desde que os headers customizados não sobrescrevam `Authorization`.

---

## 3. Matriz de disponibilidade

| Estado | Interface/histórico | OpenRouter | Qwen local |
|---|:---:|:---:|:---:|
| VPS e Mac online | sim | sim | sim |
| Mac desligado ou sem internet | **sim** | **sim** | não |
| `qwen38-official` parado, túnel do Mac online | sim | sim | não; origem retorna erro |
| Túnel do Mac parado, modelo online | sim | sim | não remotamente; continua acessível no próprio Mac |
| VPS/Open WebUI parado | não | não por esta UI | Qwen continua utilizável localmente no Mac |
| Cloudflare indisponível | não pelo domínio público | não pela UI pública | Qwen continua local no Mac |

Para evitar que uma conexão local offline torne a lista de modelos lenta:

- cadastrar `qwen38-official-omlx` em **Model IDs (Filter)** em vez de depender de `/models` a cada carregamento;
- usar timeout curto para descoberta de modelos;
- manter um modelo OpenRouter como default;
- configurar modelos auxiliares/tarefas do Open WebUI para um modelo remoto, não para o Qwen doméstico.

Com filtro manual, o nome do Qwen pode continuar aparecendo quando o Mac estiver offline; selecionar o modelo produzirá erro de conexão. Isso é esperado e preferível a bloquear a interface inteira.

---

## 4. Requisitos e decisões antes da instalação

### 4.1 Contas e infraestrutura

- domínio `seudominio.com` ativo no Cloudflare, com a zona em status **Active**;
- delegação pública verificada em 25/08/2026: `jacob.ns.cloudflare.com` e `connie.ns.cloudflare.com`;
- `chat.seudominio.com` e `llm-home.seudominio.com` sem registros públicos conflitantes na mesma verificação;
- conta Cloudflare Zero Trust;
- VPS Linux com Docker Engine e Docker Compose v2;
- acesso SSH ou console à VPS;
- conta OpenRouter e API key com limite de gasto;
- Mac ligado à internet quando o Qwen local for necessário.

### 4.2 Hostnames definidos para `seudominio.com`

```text
chat.seudominio.com      → Open WebUI cloud, acesso humano
llm-home.seudominio.com  → API qwen38-official, acesso somente por Service Token
```

O apex `seudominio.com` e `www.seudominio.com` ficam livres para site, redirects ou uso futuro. Isso também evita misturar os cookies e as políticas do WebUI com outros serviços do domínio.

O e-mail permitido no Cloudflare Access **não precisa** terminar em `@seudominio.com`; use o endereço exato da sua identidade real no IdP/OTP. Na consulta pública de 25/08/2026, o domínio não publicava MX, portanto não presuma que já existe recebimento de e-mail em `@seudominio.com`. Não reutilize o mesmo hostname nem a mesma Access application para UI humana e API máquina-a-máquina. As políticas e os riscos são diferentes.

### 4.3 Capacidade inicial da VPS

Como a inferência ocorrerá no OpenRouter ou no Mac, a VPS não precisa de GPU. Para uma instância pessoal, um ponto inicial prático é:

- 2 vCPU;
- 4 GB de RAM;
- 30 GB ou mais de SSD local;
- uma única réplica/worker.

Esses números são uma recomendação operacional, não um requisito oficial rígido. Uploads, RAG, múltiplos usuários e grandes bases vetoriais exigem mais capacidade.

### 4.4 Persistência

Para uso pessoal com uma réplica e SSD local, o SQLite padrão do Open WebUI é aceitável segundo a documentação oficial. Para múltiplas réplicas ou carga maior, usar PostgreSQL e Redis.

Este guia usa:

- uma réplica;
- SQLite em volume persistente;
- JWT curto;
- Cloudflare Access na frente.

Redis é opcional, mas recomendado se for necessário revogar sessões imediatamente. Sem Redis, logout/troca de senha não revoga um JWT já emitido; ele continua válido até `JWT_EXPIRES_IN` expirar.

---

## 5. Fase 1 — preparar a VPS

> Os comandos são modelos. Substitua usuário, registry e caminhos. Os hostnames `chat.seudominio.com` e `llm-home.seudominio.com` já são os definidos. Fixe versões/digests novamente no dia da implantação.

### 5.1 Estrutura de diretórios

```bash
sudo mkdir -p /opt/open-webui/{data,secrets,backups}
sudo chown -R "$USER":"$USER" /opt/open-webui
chmod 700 /opt/open-webui /opt/open-webui/data \
  /opt/open-webui/secrets /opt/open-webui/backups
cd /opt/open-webui
umask 077
```

### 5.2 Gerar chave persistente

```bash
umask 077
printf 'WEBUI_SECRET_KEY=%s\n' "$(openssl rand -hex 32)" \
  > /opt/open-webui/secrets/open-webui.env
chmod 600 /opt/open-webui/secrets/open-webui.env
```

Essa chave assina sessões e protege alguns dados sensíveis suportados, mas **não criptografa genericamente as API keys e custom headers das conexões OpenAI-compatible**. No `v0.11.0`, essas credenciais permanecem recuperáveis da configuração persistida no banco; proteja disco, snapshots e backups como secrets. A chave deve:

- permanecer igual entre recriações do container;
- ser incluída no backup criptografado;
- nunca entrar no Git;
- ser rotacionada apenas com planejamento, pois a rotação invalida sessões.

### 5.3 Construir e fixar uma imagem não-root

A imagem oficial `v0.11.0` roda como UID 0 por padrão. O Dockerfile suporta `UID`/`GID` de build. Antes da publicação, construa a tag revisada a partir do source release, usando o UID/GID do usuário de deploy:

```bash
cd /opt/open-webui
OPENWEBUI_UID="$(id -u)"
OPENWEBUI_GID="$(id -g)"
git clone --branch v0.11.0 --depth 1 \
  https://github.com/open-webui/open-webui.git source-v0.11.0
cd source-v0.11.0
git rev-parse HEAD

docker build \
  --build-arg UID="$OPENWEBUI_UID" \
  --build-arg GID="$OPENWEBUI_GID" \
  -t local/open-webui:v0.11.0-nonroot .

docker image inspect local/open-webui:v0.11.0-nonroot \
  --format 'user={{.Config.User}} image-id={{.Id}}'
```

Faça scan da imagem. Para referência imutável, publique-a num registry privado e obtenha o `RepoDigest`; se não houver registry, registre/verifique o image ID antes de cada deploy e nunca reconstrua a mesma tag silenciosamente. O caminho recomendado usa digest.

Crie `/opt/open-webui/.env` **sem segredos**:

```dotenv
OPENWEBUI_IMAGE=<REGISTRY_PRIVADO>/open-webui-nonroot@sha256:<DIGEST_APROVADO>
CLOUDFLARED_IMAGE=cloudflare/cloudflared@sha256:<DIGEST_APROVADO>
OPENWEBUI_UID=1000
OPENWEBUI_GID=1000
```

Substitua UID/GID pelos valores de `id -u`/`id -g` e ajuste o ownership:

```bash
chown -R "$(id -u):$(id -g)" /opt/open-webui/data
chmod 700 /opt/open-webui/data
chmod 600 /opt/open-webui/.env
```

O bootstrap pode ser ensaiado com a imagem oficial enquanto a porta estiver exclusivamente em loopback, mas **não publique o hostname antes de a imagem não-root, o digest e os controles abaixo passarem**.

### 5.4 Compose inicial do Open WebUI

Exemplo para a versão estável verificada na data deste documento:

```yaml
# /opt/open-webui/compose.yaml
services:
  open-webui:
    image: "${OPENWEBUI_IMAGE:?defina OPENWEBUI_IMAGE com digest aprovado}"
    user: "${OPENWEBUI_UID:?defina OPENWEBUI_UID}:${OPENWEBUI_GID:?defina OPENWEBUI_GID}"
    container_name: open-webui
    restart: unless-stopped
    ports:
      - "127.0.0.1:3000:8080"
    volumes:
      - ./data:/app/backend/data
    env_file:
      - ./secrets/open-webui.env
    environment:
      ENV: prod
      UVICORN_WORKERS: "1"

      WEBUI_URL: "https://chat.seudominio.com"
      CORS_ALLOW_ORIGIN: "https://chat.seudominio.com"
      DEFAULT_USER_ROLE: pending

      ENABLE_PASSWORD_VALIDATION: "true"
      PASSWORD_VALIDATION_REGEX_PATTERN: "^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d)(?=.*[^\\w\\s]).{12,}$"
      PASSWORD_VALIDATION_HINT: "Mínimo de 12 caracteres com maiúscula, minúscula, número e símbolo."
      JWT_EXPIRES_IN: "4h"

      # Bootstrap local via SSH/HTTP: mantenha false somente até criar o admin.
      # Antes de publicar o hostname HTTPS, altere os dois valores para "true"
      # e recrie o container; isso é um gate obrigatório da Fase 2.
      WEBUI_SESSION_COOKIE_SECURE: "false"
      WEBUI_SESSION_COOKIE_SAME_SITE: strict
      WEBUI_AUTH_COOKIE_SECURE: "false"
      WEBUI_AUTH_COOKIE_SAME_SITE: strict

      HSTS: "max-age=31536000;includeSubDomains"
      XFRAME_OPTIONS: DENY
      XCONTENT_TYPE: nosniff
      REFERRER_POLICY: strict-origin-when-cross-origin
      PERMISSIONS_POLICY: "camera=(),microphone=(),geolocation=()"

      ENABLE_OPENAI_API_PASSTHROUGH: "false"
      ENABLE_DIRECT_CONNECTIONS: "false"
      ENABLE_COMMUNITY_SHARING: "false"
      ENABLE_PLUGINS: "false"
      ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS: "false"
      ENABLE_CODE_EXECUTION: "false"
      ENABLE_CODE_INTERPRETER: "false"
      ENABLE_WEB_SEARCH: "false"
      ENABLE_AUTOMATIONS: "false"
      ENABLE_SUBAGENTS: "false"
      ENABLE_IMAGE_GENERATION: "false"
      ENABLE_RAG_LOCAL_WEB_FETCH: "false"
      ENABLE_PROFILE_IMAGE_URL_FORWARDING: "false"
      ENABLE_API_KEYS: "false"

      RAG_FILE_MAX_SIZE: "25"
      RAG_FILE_MAX_COUNT: "5"
      RAG_ALLOWED_FILE_EXTENSIONS: ".pdf,.txt,.md,.docx,.csv"

      AUDIT_LOG_LEVEL: METADATA
      ENABLE_AUDIT_LOGS_FILE: "true"
      LOG_FORMAT: json
      GLOBAL_LOG_LEVEL: INFO

      AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST: "5"
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    pids_limit: 512
    mem_limit: 6g
    cpus: 3.0
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
```

Observações:

- A porta 3000 fica publicada somente no loopback da VPS; não abra `0.0.0.0:3000`.
- `v0.11.0` era a versão estável atual consultada em 20/08/2026. Antes de instalar, revisar releases e fixar a versão ou digest aprovado.
- Algumas opções são `ConfigVar`: depois do primeiro start, mudanças feitas no Admin Panel podem prevalecer sobre variáveis externas. Verifique o estado efetivo após cada alteração.
- Não use `WEBUI_AUTH=false` em uma instância exposta.
- A política acima desabilita tools/plugins, execução de código, web search e automações até que exista uma necessidade explícita e uma revisão de segurança.
- `user`, `cap_drop`, `no-new-privileges` e limites reduzem o blast radius. O build não-root e o ownership do volume precisam ser validados com login, migrações, upload, auditoria e backup. Não adicione `read_only` sem testar, pois o startup escreve em caminhos internos.
- Os limites de CPU/RAM/PIDs são pontos iniciais para uma VPS pessoal; ajuste com telemetria. A rotação `json-file` impede crescimento irrestrito dos logs do container.
- Não foi imposta uma CSP completa no exemplo porque uma política incorreta pode quebrar o frontend. Teste primeiro em report-only se decidir adicioná-la.

### 5.5 Subir somente o WebUI

```bash
cd /opt/open-webui
docker compose up -d open-webui
docker compose ps
docker compose logs --tail=100 open-webui
```

### 5.6 Criar o primeiro administrador sem exposição pública

Na sua máquina administrativa:

```bash
ssh -N -L 3000:127.0.0.1:3000 usuario@IP_DA_VPS
```

Abra:

```text
http://127.0.0.1:3000
```

Passos:

1. criar o primeiro usuário — ele se torna administrador;
2. usar senha longa, única e armazenada em password manager;
3. confirmar no Admin Panel que signup está desabilitado;
4. confirmar `DEFAULT_USER_ROLE=pending`;
5. não configurar ainda tools, functions, code interpreter ou busca web;
6. testar logout/login.

A versão atual desabilita signup automaticamente depois do primeiro usuário, mas isso deve ser verificado no estado efetivo.

> **Gate antes da Fase 2:** altere `WEBUI_SESSION_COOKIE_SECURE` e `WEBUI_AUTH_COOKIE_SECURE` para `"true"`, execute `docker compose up -d --force-recreate open-webui` e passe a usar somente o hostname HTTPS. Cookies `Secure` não funcionam no bootstrap HTTP local; por isso o exemplo começa temporariamente em `false`.

---

## 6. Fase 2 — proteger e publicar o Open WebUI

### 6.1 Configurar identidade no Cloudflare Access

Em **Zero Trust → Settings/Access controls → Authentication → Login methods**:

- configurar Google/GitHub/OIDC com MFA/passkey; ou
- usar One-time PIN por e-mail para um setup mais simples.

Ao usar OTP, a política deve restringir o **e-mail exato**. Não crie uma política “Login Method = One-time PIN” sem restrição de e-mail, pois isso pode permitir qualquer endereço válido.

### 6.2 Criar a Access application antes da rota

Em **Zero Trust → Access controls → Applications**:

```text
Tipo:             Self-hosted and private / public hostname
Hostname:         chat.seudominio.com
Política:         Allow
Include:          Emails → <SEU_EMAIL_EXATO_NO_IDP>
Session duration: 12h ou 24h
MFA:              habilitado no IdP, se disponível
```

Cloudflare Access é deny-by-default: somente usuários que casam com uma política Allow passam. Substitua `<SEU_EMAIL_EXATO_NO_IDP>` pelo endereço literal usado no Google/GitHub/OIDC/OTP; não use um placeholder na política real.

Não use:

- `Include Everyone`;
- `Login Methods: One-time PIN` sozinho;
- política Bypass permanente;
- wildcard de e-mail desnecessário.

### 6.3 Criar o Tunnel da VPS

Pré-check no dashboard:

```text
Websites → seudominio.com → Overview → Status: Active
SSL/TLS → Universal SSL: Active
```

Não crie manualmente registros DNS `A` ou `AAAA` apontando para a VPS. Ao salvar a Published application route, o Tunnel cria/gerencia o registro proxied correspondente para `chat.seudominio.com`. Se já existir um registro com esse nome, resolva o conflito antes.

Em **Cloudflare → Networking → Tunnels**:

```text
Create tunnel
Nome: openwebui-cloud
Tipo: cloudflared
Ambiente: Docker
```

Copie o token uma única vez para um arquivo privado sem colocá-lo no histórico:

```bash
cd /opt/open-webui
umask 077
read -r -s TUNNEL_TOKEN
printf '%s' "$TUNNEL_TOKEN" > secrets/cloudflare-ui-tunnel.token
unset TUNNEL_TOKEN
chmod 600 secrets/cloudflare-ui-tunnel.token
```

### 6.4 Adicionar `cloudflared` ao Compose

```yaml
# acrescentar em services:
  cloudflared:
    image: "${CLOUDFLARED_IMAGE:?defina CLOUDFLARED_IMAGE com digest aprovado}"
    container_name: cloudflared-open-webui
    restart: unless-stopped
    depends_on:
      - open-webui
    command:
      - tunnel
      - --no-autoupdate
      - run
      - --token-file
      - /run/secrets/tunnel_token
    secrets:
      - tunnel_token
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    pids_limit: 128
    mem_limit: 256m
    cpus: 1.0
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"

# acrescentar no nível raiz:
secrets:
  tunnel_token:
    file: ./secrets/cloudflare-ui-tunnel.token
```

Os placeholders `${OPENWEBUI_IMAGE}` e `${CLOUDFLARED_IMAGE}` devem conter referências por **digests imutáveis**, por exemplo:

```dotenv
OPENWEBUI_IMAGE=<REGISTRY_PRIVADO>/open-webui-nonroot@sha256:<DIGEST_APROVADO>
CLOUDFLARED_IMAGE=cloudflare/cloudflared@sha256:<DIGEST_APROVADO>
```

Registre versão, digest, data de aprovação e resultado do scanner. Em containers, atualização é feita trocando deliberadamente o digest; `--no-autoupdate` evita atualização dentro do container.

Subir:

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=100 cloudflared
```

### 6.5 Criar a published application route

No Tunnel `openwebui-cloud`:

```text
Route type:  Published application
Hostname:    chat.seudominio.com
Service URL: http://open-webui:8080
```

Em **Additional application settings**, habilite **Protect with Access** e selecione/configure a aplicação correspondente. Isso faz `cloudflared` validar o Access JWT antes de encaminhar ao origin.

### 6.6 Testes do WebUI público

Com 4G/5G no celular:

1. abrir `https://chat.seudominio.com`;
2. confirmar a tela Cloudflare Access;
3. autenticar com o e-mail permitido;
4. confirmar o login separado do Open WebUI;
5. testar logout/login;
6. abrir em aba anônima e confirmar que Access aparece novamente;
7. tentar outro e-mail e confirmar negação.

Teste negativo de rede:

```bash
# Da internet, isto não deve responder:
curl http://IP_PUBLICO_DA_VPS:3000
```

A VPS deve bloquear portas não necessárias no firewall/security group. O acesso ao WebUI deve ocorrer apenas pelo Tunnel.

---

## 7. Fase 3 — configurar OpenRouter

### 7.1 Criar uma chave dedicada

No OpenRouter:

1. criar uma API key exclusiva para essa instância;
2. definir limite de crédito/gasto;
3. não usar a chave principal da conta;
4. armazená-la apenas no Open WebUI/secret manager;
5. rotacionar se houver suspeita de exposição;
6. revisar retenção, logging e uso para treinamento de cada provedor selecionado — OpenRouter é um roteador, e a política efetiva também depende do provedor final.

### 7.2 Adicionar a conexão

No Open WebUI:

```text
Admin Settings → Connections → OpenAI → Add Connection
```

Preencher:

```text
URL:       https://openrouter.ai/api/v1
API Key:   sk-or-...
Prefix ID: openrouter          # recomendado para evitar colisões
```

Em **Model IDs (Filter)**, adicionar somente os modelos desejados. O OpenRouter expõe milhares de modelos; carregar tudo polui o seletor e torna o painel mais lento.

Exemplos de IDs devem ser confirmados no catálogo atual do OpenRouter antes do cadastro. Não copie IDs antigos sem verificar disponibilidade e preço.

### 7.3 Modelo default e tarefas auxiliares

Para o Open WebUI continuar funcional quando o Mac estiver offline:

- escolher um modelo OpenRouter como modelo default;
- escolher um modelo remoto barato/rápido para títulos, tags e outras tarefas auxiliares;
- não usar `qwen38-official-omlx` como único modelo default;
- manter allowlist pequena.

### 7.4 Teste de independência do Mac

Antes de integrar o Qwen doméstico:

1. parar/desligar o Mac;
2. acessar o WebUI pelo celular;
3. criar um chat com um modelo OpenRouter;
4. confirmar streaming e persistência do histórico;
5. reiniciar o WebUI e confirmar dados e login.

Esse teste demonstra que a continuidade vem da hospedagem real na VPS, não do Tunnel.

---

## 8. Fase 4 — publicar somente a API mínima do Qwen local

Essa fase altera a postura de exposição do modelo: o serviço continuará em loopback, mas ganhará um hostname público protegido por duas autenticações. Faça apenas depois de validar Open WebUI e OpenRouter.

### 8.1 Pré-condições no Mac

Conclua primeiro o guia clean-room, incluindo verificação criptográfica, smoke com MTP e canário real de 40000 tokens. Só então:

```bash
PROFILE="$HOME/models/qwen38-official-omlx"
qwen38-official verify
qwen38-official start
qwen38-official status
lsof -nP -iTCP:8084 -sTCP:LISTEN
"$PROFILE/runtime/venv/bin/python" "$PROFILE/context-canary.py" \
  --prompt-tokens 40000 --max-tokens 4 --require-mtp
```

O listener deve permanecer:

```text
127.0.0.1:8084
```

Nunca mudar para:

```text
0.0.0.0:8084
```

O Tunnel se conecta ao loopback como processo local; não é necessário abrir firewall ou roteador.

### 8.2 Criar Service Token para a VPS

Em:

```text
Zero Trust → Access controls → Service credentials → Service Tokens
```

Criar:

```text
Nome:     openwebui-cloud-to-qwen-home
Duração:  definida e revisável; configurar alerta antes da expiração
```

Salvar imediatamente:

- Client ID;
- Client Secret.

O secret aparece apenas uma vez. Guardar no secret manager e nunca no Git.

### 8.3 Criar Access application da API local

Criar antes da rota pública:

```text
Tipo:      Self-hosted
Hostname:  llm-home.seudominio.com
Ação:      Service Auth
Include:   Service Token → openwebui-cloud-to-qwen-home
401 for Service Auth: habilitado
```

Não adicionar política humana Allow, `Everyone` ou Bypass nesse hostname. A API foi desenhada para uma única identidade de serviço.

### 8.4 Criar Tunnel no Mac

Assim como no hostname do chat, não crie `A`/`AAAA` apontando para o IP residencial. A Published application route do Tunnel gerencia o DNS proxied de `llm-home.seudominio.com`; remova ou renomeie qualquer registro conflitante antes de salvar.

```text
Networking → Tunnels → Create tunnel
Nome: qwen-home
Tipo: cloudflared
Sistema: macOS arm64
```

A rota será criada depois da aplicação Access:

```text
Hostname:    llm-home.seudominio.com
Service URL: http://127.0.0.1:8084
Protect with Access: habilitado
```

### 8.5 Executar `cloudflared` no Mac

#### Caminho obrigatório: token em arquivo

Não execute o comando copiado do dashboard com o token literal. Ele pode parar no histórico e no `argv` do processo. Extraia o token pela interface apenas para gravá-lo diretamente em um arquivo owner-only — sem eco, screenshot ou linha de comando literal — e depois feche/limpe o clipboard.

Use `cloudflared >= 2025.4.0` com `--token-file`, mantendo o token em arquivo `0600`, e um LaunchAgent do usuário. Isso evita o token literal nos argumentos do processo.

Estrutura sugerida:

```text
~/.config/cloudflared-qwen/tunnel.token           modo 0600
~/Library/LaunchAgents/com.local.cloudflared-qwen.plist
~/Library/Logs/cloudflared-qwen.{out,err}.log
```

Exemplo de `ProgramArguments` no LaunchAgent:

```xml
<array>
  <string>/opt/homebrew/bin/cloudflared</string>
  <string>tunnel</string>
  <string>--loglevel</string>
  <string>info</string>
  <string>run</string>
  <string>--token-file</string>
  <string>/Users/SEU_USUARIO/.config/cloudflared-qwen/tunnel.token</string>
</array>
```

Use o caminho retornado por `command -v cloudflared`; não presuma `/opt/homebrew/bin` em Intel Mac ou instalações diferentes.

O LaunchAgent inicia após login do usuário. Isso combina com o modelo MLX/Metal, que também deve executar no contexto do usuário. Não habilite login automático apenas para iniciar o modelo.

O processo `qwen38-official` tem egress bloqueado por sandbox; isso não impede o Tunnel, porque `cloudflared` é outro processo que recebe conexões da Cloudflare e chama `127.0.0.1:8084` localmente.

### 8.6 Logs

Mantenha `cloudflared` em `info`. Não use `debug` continuamente: a documentação alerta que debug registra URL, método e headers, podendo expor credenciais.

---

## 9. Fase 5 — conectar o Open WebUI cloud ao Qwen

### 9.1 Testar as duas autenticações fora do WebUI

Na VPS, grave os três valores em arquivos `0600` por secret manager ou entrada silenciosa; não use `export SEGREDO='...'`, pois isso pode ir ao histórico. Para o teste, use um arquivo de configuração temporário `0600` e passe somente seu caminho ao `curl`, evitando headers secretos no `argv`:

```bash
umask 077
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT INT TERM

# Estes arquivos devem vir do secret manager/entrada silenciosa, nunca do Git:
CF_ID_FILE=/run/secrets/cf_access_client_id
CF_SECRET_FILE=/run/secrets/cf_access_client_secret
QWEN_KEY_FILE=/run/secrets/qwen_api_key

{
  printf 'silent\nshow-error\nfail-with-body\n'
  printf 'url = "https://llm-home.seudominio.com/v1/models"\n'
  printf 'header = "CF-Access-Client-Id: %s"\n' "$(<"$CF_ID_FILE")"
  printf 'header = "CF-Access-Client-Secret: %s"\n' "$(<"$CF_SECRET_FILE")"
  printf 'header = "Authorization: Bearer %s"\n' "$(<"$QWEN_KEY_FILE")"
} > "$TEST_DIR/positive.curlrc"
chmod 600 "$TEST_DIR/positive.curlrc"
curl --config "$TEST_DIR/positive.curlrc"
```

Deve retornar `qwen38-official-omlx`. Não use `set -x`, não imprima o arquivo e confirme que os logs/`ps` não contêm os valores.

Testes negativos usam o mesmo padrão e novos arquivos temporários:

```bash
# Sem Service Token: deve ser negado no Cloudflare Access.
{
  printf 'silent\nshow-error\ninclude\n'
  printf 'url = "https://llm-home.seudominio.com/v1/models"\n'
  printf 'header = "Authorization: Bearer %s"\n' "$(<"$QWEN_KEY_FILE")"
} > "$TEST_DIR/no-access-token.curlrc"
curl --config "$TEST_DIR/no-access-token.curlrc"

# Com Service Token, mas sem Bearer do Qwen: deve ser negado no origin.
{
  printf 'silent\nshow-error\ninclude\n'
  printf 'url = "https://llm-home.seudominio.com/v1/models"\n'
  printf 'header = "CF-Access-Client-Id: %s"\n' "$(<"$CF_ID_FILE")"
  printf 'header = "CF-Access-Client-Secret: %s"\n' "$(<"$CF_SECRET_FILE")"
} > "$TEST_DIR/no-qwen-key.curlrc"
curl --config "$TEST_DIR/no-qwen-key.curlrc"
```

O `trap` remove os arquivos temporários. Em ambiente com outros usuários/root não confiáveis, execute-os em tmpfs privado ou diretamente no secret manager. Se qualquer token já foi digitado literalmente em comando, trate-o como exposto e rotacione Tunnel Token, Service Token e Qwen key.

### 9.2 Configurar a conexão no Open WebUI

No Admin Panel:

```text
Admin Settings → Connections → OpenAI → Add Connection
```

Campos:

```text
URL:       https://llm-home.seudominio.com/v1
API Key:   conteúdo de ~/models/qwen38-official-omlx/state/api-key no Mac
Prefix ID: local                         # produz local.qwen38-official-omlx
Model IDs (Filter): qwen38-official-omlx  # recomendado
```

Em **Advanced / Custom Headers**:

```json
{
  "CF-Access-Client-Id": "<CLIENT_ID>",
  "CF-Access-Client-Secret": "<CLIENT_SECRET>"
}
```

Não coloque `Authorization` em Custom Headers. O campo **API Key** já produz:

```text
Authorization: Bearer <QWEN_API_KEY>
```

O filtro manual evita uma consulta contínua ao `/models` quando o Mac estiver offline. Com o prefixo normativo `local`, o ID no seletor/workspace é `local.qwen38-official-omlx`, igual ao usado pela compactação do guia clean-room. Se mudar o prefixo, atualize também workspace model, ACL e `CONTEXT_COMPACTION_MODEL`.

### 9.3 Testar streaming

1. selecionar o Qwen no Open WebUI;
2. enviar um prompt curto;
3. confirmar streaming progressivo;
4. conferir `qwen38-official status` no Mac;
5. verificar que a requisição aparece no log sem headers/segredos;
6. testar uma resposta longa o bastante para exercitar SSE.

O perfil atual usa keepalive SSE em chunks. Isso ajuda a evitar timeout por inatividade; prompts muito longos ainda devem ser testados porque um TTFT sem chunks por tempo excessivo pode atingir limites de proxy.

---

## 10. Comportamento quando o Mac estiver offline

### 10.1 Teste de failover funcional

1. deixar o Open WebUI/VPS online;
2. parar o modelo:
   ```bash
   qwen38-official stop
   ```
3. opcionalmente parar o Tunnel do Mac;
4. recarregar `https://chat.seudominio.com`;
5. confirmar que login, histórico e OpenRouter funcionam;
6. selecionar o Qwen e confirmar erro controlado;
7. iniciar novamente modelo e Tunnel;
8. confirmar que uma nova conversa Qwen funciona.

### 10.2 O que não existe automaticamente

Open WebUI não transforma `qwen38-official-omlx` em OpenRouter quando ele fica offline. Para fallback automático de um mesmo alias seria necessário:

- gateway como LiteLLM;
- regra de roteamento explícita;
- modelos semanticamente substituíveis;
- política de custo e privacidade.

Para a primeira versão, prefira seleção explícita de modelo. É mais simples e evita enviar inadvertidamente um prompt privado a um provedor remoto.

---

## 11. Hardening obrigatório

### 11.1 Cloudflare

- criar Access application antes de cada route;
- UI: Allow somente e-mail/IdP exato;
- API: Service Auth somente para token específico;
- habilitar **Protect with Access** nos dois origins;
- nunca usar Bypass permanente;
- configurar alerta de expiração do Service Token;
- revisar Access logs;
- aplicar rate limiting/WAF onde o plano permitir;
- não publicar IP residencial nem portas 3000/8084;
- revogar token do Tunnel ou Service Token imediatamente se vazar.

### 11.2 Open WebUI

- manter versão fixada;
- uma réplica/worker enquanto usar SQLite;
- signup fechado após o admin;
- senha forte e Cloudflare Access na frente;
- JWT curto ou Redis para revogação;
- cookies Secure/SameSite;
- CORS somente para o domínio real;
- `ENABLE_OPENAI_API_PASSTHROUGH=false`;
- `ENABLE_DIRECT_CONNECTIONS=false`;
- plugins, pip automático, código, tools e web search desligados até revisão;
- chave OpenRouter dedicada com limite de gasto;
- allowlist de modelos e provedores cuja política de retenção/treinamento seja aceitável;
- política explícita de retenção para chats, uploads, Access logs, audit logs e backups;
- audit logs somente `METADATA` para não registrar prompts/respostas;
- limites de upload/CPU/RAM/PIDs, rotação de logs e alerta de disco antes de 80%;
- proteger o diretório de dados e secrets.

### 11.3 Mac/Qwen

- manter `127.0.0.1:8084`;
- manter Bearer authentication;
- não ampliar a fachada mínima;
- manter egress negado;
- não habilitar MCP, remote code, web, tools ou model mutation;
- manter concorrência 1 ou definir rate limit compatível;
- conservar o próprio diretório `qwen38-official-omlx` e o rollback operacional coerente em `32768` documentado no guia clean-room;
- executar `qwen38-official verify --quick` antes de iniciar e a verificação completa após instalação/restore;
- não copiar o API key para documentos, chat ou screenshots.

### 11.4 Segredos na VPS

A VPS/Open WebUI armazenará — inclusive em configuração persistida recuperável no banco —:

- API key do OpenRouter;
- Qwen Bearer key;
- Cloudflare Access Client ID/Secret;
- WebUI secret key;
- Tunnel token da VPS.

Um administrador root da VPS pode acessar esses dados. Use:

- fornecedor cloud confiável;
- disco criptografado quando disponível;
- arquivos `0600`, diretórios `0700` e criptografia de disco/snapshots quando disponível;
- backups criptografados;
- chaves separadas e rotacionáveis;
- nenhuma credencial em Git ou Compose público.

Se o Open WebUI for comprometido, revogar:

1. Service Token `openwebui-cloud-to-qwen-home`;
2. Qwen API key;
3. OpenRouter API key;
4. sessões/chave do Open WebUI conforme impacto.

---

## 12. Privacidade e fluxo de dados

### OpenRouter

Ao selecionar OpenRouter:

```text
Celular → Cloudflare → VPS/Open WebUI → OpenRouter → provedor escolhido
```

O prompt sai da sua infraestrutura e fica sujeito às políticas de OpenRouter e do provedor escolhido.

### Qwen local

Ao selecionar o Qwen:

```text
Celular → Cloudflare → VPS/Open WebUI → Cloudflare → Tunnel → Mac/Qwen
```

Os pesos e a inferência permanecem no Mac, mas:

- o prompt passa pela VPS;
- TLS é terminado/processado na infraestrutura Cloudflare;
- histórico fica armazenado na VPS/Open WebUI;
- o provedor da VPS controla o host e pode, tecnicamente, acessar memória/disco.

Se a exigência for que nem Cloudflare nem VPS possam observar prompts em claro, essa arquitetura não atende; seria necessário outro modelo de confiança, tipicamente VPN ou criptografia de aplicação ponta a ponta.

---

## 13. Backup, atualização e rollback

### 13.1 Backup

O diretório `/app/backend/data` contém banco, usuários, chats, uploads, configurações e credenciais de conexões. **Todo o backup precisa ser criptografado**, não apenas `secrets/`. Não mantenha `.tar.gz` plaintext. Prefira `restic` ou `borg`; outra opção é stream de `tar` diretamente para `age`. O exemplo pressupõe que o DB esteja em `data/webui.db`; confirme o caminho no release implantado antes de automatizar:

```bash
cd /opt/open-webui
set -euo pipefail
umask 077
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/opt/open-webui/backups/open-webui-$STAMP.tar.gz.age"
PARTIAL="$BACKUP.partial"
RECIPIENT='age1SUBSTITUA_PELA_CHAVE_PUBLICA_DO_BACKUP'
IDENTITY='/CAMINHO/PRIVADO/backup-identity.txt'

RESTORE_CHECK="$(mktemp -d)"
restart_webui() { docker compose start open-webui >/dev/null || true; }
cleanup() { rm -f "$PARTIAL"; rm -rf "$RESTORE_CHECK"; restart_webui; }
trap cleanup EXIT INT TERM

docker compose stop open-webui
tar -C /opt/open-webui -czf - data secrets \
  | age -r "$RECIPIENT" -o "$PARTIAL"
age -d -i "$IDENTITY" "$PARTIAL" | tar -tzf - \
  | grep -qE '(^|/)data/webui\.db$'
age -d -i "$IDENTITY" "$PARTIAL" \
  | tar -xzf - -C "$RESTORE_CHECK" data/webui.db
test "$(sqlite3 "$RESTORE_CHECK/data/webui.db" 'PRAGMA integrity_check;')" = 'ok'
mv "$PARTIAL" "$BACKUP"
sha256sum "$BACKUP" > "$BACKUP.sha256"
rm -rf "$RESTORE_CHECK"
docker compose start open-webui
trap - EXIT INT TERM
```

A chave privada de backup deve ficar fora da VPS. Defina e registre:

- backup diário e antes de toda atualização;
- retenção sugerida inicial: 7 diários, 4 semanais e 6 mensais;
- RPO inicial de 24 h e RTO de 2 h, ajustados à necessidade;
- alerta de falha;
- teste de restore trimestral em volume/instância isolada;
- política de exclusão para que backups expirados não reintroduzam chats já eliminados.

Não trate o próprio disco da VPS como backup. Copie os arquivos cifrados para storage independente com versionamento.

### 13.2 Política de retenção e privacidade

Antes do go-live, registre uma decisão explícita, por exemplo:

| Dado | Retenção inicial | Acesso |
|---|---:|---|
| Chats/uploads | até exclusão pelo usuário ou 90 dias | usuário e admin root-equivalent |
| Audit log `METADATA` | 30 dias | administrador |
| Cloudflare Access logs | conforme plano, revisar no dashboard | administradores Cloudflare |
| Backups diários | 7 diários + 4 semanais + 6 mensais | operador com chave `age` |

A tabela é um ponto de partida, não obrigação legal. Adeque ao conteúdo e à jurisdição. Teste exclusão e assegure que a expiração de backups não reintroduza dados eliminados. Para OpenRouter, registre os provedores aprovados e suas políticas de retenção/treinamento.

### 13.3 Atualização

1. revisar release notes;
2. criar backup consistente e provar que ele descriptografa/lista;
3. manter `UVICORN_WORKERS=1` durante migrações;
4. trocar para novo digest aprovado;
5. `docker compose pull`;
6. `docker compose up -d`;
7. verificar logs, login, histórico, OpenRouter e Qwen;
8. somente então remover imagem antiga e, após a retenção definida, o backup anterior.

Migrações de banco podem ser unidirecionais. Voltar apenas a imagem pode não funcionar; o rollback real pode exigir restaurar o backup anterior.

### 13.4 Restore e rollback de versão

Procedimento testável:

1. interromper Open WebUI e conservar o estado falho com timestamp, sem sobrescrevê-lo;
2. criar um volume/diretório vazio de restauração;
3. verificar SHA-256 e descriptografar o backup diretamente para esse destino;
4. restaurar `data` e o conjunto de secrets correspondente à mesma data;
5. configurar a imagem antiga pelo **digest** preservado junto ao backup;
6. iniciar uma única réplica/worker;
7. validar login, histórico, OpenRouter, custom headers e Qwen;
8. só então promover o diretório restaurado e arquivar o estado falho.

Teste esse runbook numa instância separada antes de depender dele. Uma imagem antiga com banco já migrado não é rollback; ambos precisam voltar ao mesmo ponto compatível.

### 13.5 Rollback do acesso local

Para retirar o Qwen da cloud sem afetar o modelo local:

1. desabilitar/remover a conexão no Open WebUI;
2. revogar o Service Token;
3. remover a route `llm-home.seudominio.com`;
4. parar/desabilitar o `cloudflared` do Mac.

`qwen38-official` continuará funcionando localmente em `127.0.0.1:8084`; remover o Tunnel não remove nem altera o perfil.

---

## 14. Observabilidade e operação

### VPS

```bash
cd /opt/open-webui
docker compose ps
docker compose logs --tail=100 open-webui
docker compose logs --tail=100 cloudflared
```

### Mac

```bash
qwen38-official status
qwen38-official logs
lsof -nP -iTCP:8084 -sTCP:LISTEN
```

### Cloudflare

Verificar:

- Tunnel `openwebui-cloud`: Healthy;
- Tunnel `qwen-home`: Healthy quando o Mac estiver online;
- Access logs da UI;
- Access logs da Service Auth;
- expiração do Service Token;
- falhas e volume anormal de requests.

Não registrar bodies de prompts em audit logs. `METADATA` é suficiente para o primeiro rollout.

---

## 15. Checklist de aceitação

### Open WebUI cloud

- [ ] containers usam digests `sha256` aprovados e registrados;
- [ ] volume persistente existe;
- [ ] WebUI secret está protegido e em backup;
- [ ] primeira conta é admin;
- [ ] signup está desabilitado;
- [ ] porta 3000 está apenas em `127.0.0.1` na VPS;
- [ ] Cloudflare Access exige o e-mail correto;
- [ ] usuário não autorizado é negado;
- [ ] após o bootstrap, ambos os cookies estão `Secure=true` e CORS está restrito;
- [ ] plugins, código, tools e passthrough estão desligados;
- [ ] limites de upload/CPU/RAM/PIDs e rotação de logs estão efetivos;
- [ ] backup é cifrado, tem retenção/RPO/RTO e restore foi testado.

### OpenRouter

- [ ] key exclusiva e com limite de gasto;
- [ ] allowlist pequena de modelos;
- [ ] modelo remoto é default;
- [ ] funciona com o Mac desligado;
- [ ] custos e políticas de dados foram revisados.

### Qwen local remoto

- [ ] guia clean-room do `fcmeyer@0299356…` foi concluído;
- [ ] `qwen38-official verify` criptográfico passa;
- [ ] smoke registra Lightning MTP ativo e o canário 40K passa;
- [ ] `qwen38-official verify --quick` passa em cada start;
- [ ] listener continua em `127.0.0.1:8084`;
- [ ] Access app usa Service Auth, não Allow/Bypass;
- [ ] Service Token é específico e tem alerta de expiração;
- [ ] Protect with Access está habilitado;
- [ ] request sem Service Token é negado;
- [ ] request sem Qwen Bearer é negado;
- [ ] request com ambos retorna `/v1/models`;
- [ ] chat via WebUI faz streaming;
- [ ] Mac offline não derruba OpenRouter/WebUI;
- [ ] nenhum segredo aparece em logs ou processos.

---

## 16. Sequência de implantação recomendada

1. escolher VPS, domínio e hostnames;
2. instalar Docker/Compose na VPS;
3. subir Open WebUI pinado apenas no loopback;
4. criar admin por túnel SSH e fechar signup;
5. criar Access application humana;
6. criar Tunnel da VPS e publicar somente o WebUI;
7. testar acesso móvel e negações;
8. configurar OpenRouter e provar funcionamento com Mac desligado;
9. criar Service Token e Access application da API local;
10. criar Tunnel do Mac para `127.0.0.1:8084`;
11. testar as duas autenticações via `curl`;
12. adicionar conexão Qwen com custom headers e model filter;
13. testar streaming e comportamento offline;
14. configurar backup, alertas e procedimento de rotação;
15. somente depois considerar auto-start de Tunnel e modelo.

Essa ordem evita publicar uma aplicação sem Access e preserva uma rota de rollback em cada fase.

---

## 17. Custos e dependências

| Item | Custo possível |
|---|---|
| Domínio | anual |
| VPS | mensal |
| Cloudflare Tunnel/Access | depende do plano e limites atuais |
| OpenRouter | por uso/modelo |
| Armazenamento de backup | por volume/egress |
| Energia do Mac | enquanto o modelo local estiver disponível |

Não fixe valores neste documento: preços e limites mudam. Conferir as páginas comerciais no dia da implantação.

---

## 18. Referências oficiais

### Open WebUI

- Quick Start: <https://docs.openwebui.com/getting-started/quick-start/>
- OpenAI-compatible providers: <https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/>
- Hardening: <https://docs.openwebui.com/getting-started/advanced-topics/hardening/>
- Environment variables: <https://docs.openwebui.com/reference/env-configuration/>
- Updating/backup: <https://docs.openwebui.com/getting-started/updating/>
- Releases: <https://github.com/open-webui/open-webui/releases>
- Backend `v0.11.0` com Bearer + custom headers: <https://raw.githubusercontent.com/open-webui/open-webui/v0.11.0/backend/open_webui/routers/openai.py>

### Cloudflare

- Create remotely managed Tunnel: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/>
- Publish self-hosted application with Access: <https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/>
- Access policies: <https://developers.cloudflare.com/cloudflare-one/access-controls/policies/>
- Service Tokens: <https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/>
- Protect origin with Access: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/#access>
- Tunnel run parameters/token-file: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/>
- Run cloudflared as macOS service: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/macos/>

### OpenRouter

- Authentication: <https://openrouter.ai/docs/api/reference/authentication>
- API keys: <https://openrouter.ai/keys>

---

## 19. Conclusão

Este runbook usa deliberadamente uma VPS porque o requisito é manter o Open WebUI e o OpenRouter disponíveis sem o Mac. Cloudflare Tunnel sozinho não oferece essa hospedagem.

A arquitetura recomendada mantém a interface e o histórico na cloud, usa OpenRouter como caminho sempre disponível e trata o M3 Max como um provedor de inferência intermitente. O endpoint doméstico não abre porta no roteador e continua preso a loopback; a VPS chega a ele por um Tunnel protegido por Service Auth e pela API key do próprio Qwen.

Isso entrega o comportamento desejado:

- celular acessa por HTTPS sem VPN;
- Open WebUI e OpenRouter funcionam com o Mac desligado;
- o Qwen local aparece quando o Mac está online;
- os pesos nunca saem do M3 Max;
- cada camada pode ser desativada e revogada independentemente.
