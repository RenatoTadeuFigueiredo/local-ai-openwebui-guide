# Navegador universal HITL multiusuário: arquitetura, POC e publicação restrita

**Estado em 26/08/2026:** POC local validado para admin e user-a; portal publicado separadamente em `browser.seudominio.com` com Cloudflare Access/OTP; E2E móvel de baixo risco ainda pendente  
**Open WebUI:** `0.11.0`  
**Backend do POC:** Python `3.12`, FastAPI, Playwright `1.62.0`, Chromium `151.0.7922.71`, SQLite, Xvfb, x11vnc e noVNC  
**Objetivo:** permitir que o agente navegue em sites arbitrários, pause em login/MFA/CAPTCHA, entregue a mesma aba ao usuário e retome com a sessão persistida

> Este documento descreve um **POC publicado com acesso restrito**, não uma autorização para usar contas de alto valor. O primeiro teste móvel deve usar um site descartável ou serviço de baixo impacto. Google principal, Gmail real, Drive real, bancos, saúde, governo e consoles de produção permanecem fora do escopo inicial.
>
> O Model ID `local.qwen38-omlx` citado aqui pertence à implantação uncensored atual descrita em [`02-open-webui-sem-vps-macos-cloudflare.md`](02-open-webui-sem-vps-macos-cloudflare.md). Uma migração para o perfil recomendado `local.qwen38-official-omlx` exige atualizar conexão, ACL, compactação e canários; a configuração abaixo não é evidência independente do checkpoint novo.

---

## 1. Resultado entregue

O POC implementa:

- uma identidade de navegador persistente para admin;
- uma identidade separada e persistente para user-a;
- vínculo pelo UUID imutável da conta autenticada no Open WebUI;
- Chromium e diretório `user-data-dir` separados por usuário;
- uma sessão ativa por perfil;
- a mesma janela, aba, processo Chromium e perfil no handoff;
- lock durável entre agente e humano;
- bloqueio `HTTP 423 Locked` para ações e observações do agente durante takeover;
- link curto de takeover, com token armazenado apenas como hash no SQLite;
- CSRF, cookie de sessão humana e verificação de `Origin`;
- noVNC iniciado somente após o humano assumir o controle;
- encerramento de x11vnc/websockify quando o humano devolve o controle;
- retorno explícito `READY_TO_RESUME` e nova lease antes de o agente continuar;
- persistência de cookies, `localStorage`, IndexedDB e demais dados do perfil no volume Docker;
- proxy de saída que bloqueia loopback, redes privadas, link-local, metadata e portas não web;
- Tool nativa do Open WebUI visível apenas para admin e user-a;
- Rich UI persistida que explica o takeover sem devolver URL/token ao contexto do modelo;
- painel transitório criado pela própria Tool via evento oficial `execute`, no contexto principal do Open WebUI, com botão **Assumir navegador**; o clique humano abre uma aba limpa sem herdar o sandbox da Rich UI.

O fluxo validado é:

```text
AGENT_ACTIVE
    │ agente encontra login/MFA/CAPTCHA
    ▼
WAITING_FOR_HUMAN
    │ usuário abre Rich UI e assume
    ▼
HUMAN_ACTIVE
    │ ações e observações do agente retornam 423
    │ usuário autentica na mesma aba
    ▼
READY_TO_RESUME
    │ novo turno chama browser_resume
    ▼
AGENT_ACTIVE com nova epoch
```

---

## 2. Topologia implementada

```text
chat.seudominio.com
      │ usuário autenticado no Open WebUI
      ▼
Tool Python nativa: browser_hitl_private
      │ UUID vindo de __user__, nunca do modelo
      │ chave global cifrada nas Valves do Open WebUI
      ▼
127.0.0.1:3210
Browser HITL Broker
      ├── SQLite de estado + epochs + grants
      ├── perfil persistente UUID A → admin
      ├── perfil persistente UUID B → user-a
      ├── Playwright/CDP privado
      ├── Xvfb privado
      ├── x11vnc/noVNC somente em HUMAN_ACTIVE
      └── proxy de egress com bloqueio de destinos privados
```

O container publica somente `127.0.0.1:3210` no Mac. CDP, VNC, websockify, Xvfb e proxy de saída ficam internos ao container. O Cloudflare Tunnel encaminha exclusivamente `browser.seudominio.com` para esse loopback e o hostname é protegido por Access/OTP no edge e por validação JWT novamente no origin; `chat.seudominio.com` continua sem Access.

O `Computer admin` anterior permanece separado e inalterado em `127.0.0.1:3011` e não foi publicado remotamente.

---

## 3. Identidade e isolamento

A Tool recebe estes valores do próprio Open WebUI:

- `__user__["id"]`;
- `__user__["name"]`;
- `__user__["role"]`;
- `__metadata__["chat_id"]`.

Nenhum método expõe `user_id`, e-mail ou nome de perfil como argumento controlável pelo modelo. A Tool converte a identidade autenticada em headers internos; o broker valida essa identidade e filtra todos os objetos por proprietário.

Estado atual da ACL:

| Usuário | Tool visível | Pode ler Valves/segredo |
|---|---:|---:|
| admin | sim | sim, por ser root-equivalente |
| user-a | sim | não (`401`) |
| user-b | não | não (`401`) |
| user-c | não | não (`401`) |
| user-d | não | não (`401`) |

Cada perfil recebe:

- `profile_id` opaco;
- slot interno exclusivo;
- diretório próprio, modo `0700`;
- processo Chromium próprio quando ativo;
- persistência independente no volume `openwebui-browser-hitl-poc_browser-hitl-poc-data`.

A conta Open WebUI identifica o **dono do perfil**. A conta Google/Facebook/LinkedIn usada dentro dele será aquela que o próprio usuário escolher no takeover.

---

## 4. Persistência do login

O `user-data-dir` do Chromium fica em:

```text
/data/browser-hitl/profiles/<profile-id-opaco>
```

Esse diretório sobrevive a:

- fechamento da aba;
- fim do chat;
- reinicialização do broker;
- recriação do container via Compose;
- reinicialização do Mac, desde que o volume não seja removido.

Assim, depois que admin autenticar em uma conta Google no perfil dele, cookies e armazenamento permanecem naquele perfil. user-a possui outro diretório e não recebe esses dados.

Persistência não significa login eterno. O site ainda pode pedir autenticação novamente por expiração, política corporativa, mudança de risco, revogação, senha alterada ou detecção de automação.

> Não use `docker compose down -v`. O parâmetro `-v` remove o volume e apaga os perfis persistentes.

---

## 5. Exclusão mútua e epochs

O estado fica em SQLite com `BEGIN IMMEDIATE`, WAL, `foreign_keys=ON` e transições compare-and-swap. Cada sessão possui uma `epoch` monotonicamente crescente.

Toda ação do agente envia:

- `session_id`;
- `epoch` atual;
- identidade autenticada, injetada pela Tool.

O broker verifica o estado antes da ação e novamente antes de publicar o resultado. Durante `WAITING_FOR_HUMAN` e `HUMAN_ACTIVE`:

- `navigate` falha;
- `snapshot` falha;
- `click` falha;
- `type` falha;
- uma epoch antiga falha;
- o agente não recebe screenshot, DOM, texto da página nem eventos de rede.

Ao devolver o controle, o estado é `READY_TO_RESUME`; ainda não há automação. Um novo turno chama `browser_resume`, que emite outra epoch e só então restaura `AGENT_ACTIVE`.

Se o broker reiniciar durante takeover, ele revoga grants ativos e recupera para `READY_TO_RESUME`, nunca diretamente para o agente. Na retomada, o runtime/Xvfb/Chromium precisa subir antes da transição durável para `AGENT_ACTIVE`; uma falha mantém `READY_TO_RESUME` para retry seguro. Locks e sockets X stale são removidos somente após confirmar que nenhum servidor X aceita conexão naquele display.

---

## 6. Segurança do takeover

O grant de takeover:

- usa 32 bytes aleatórios URL-safe;
- pode ser resgatado por até cinco minutos no POC;
- depois do resgate, o prazo do link não interrompe uma autenticação humana em andamento; o lock permanece até conclusão explícita ou recuperação fail-closed;
- é persistido apenas como SHA-256;
- pertence a um `user_id`, `session_id` e `epoch` específicos;
- só pode ser resgatado uma vez;
- exige `POST`, CSRF e `Origin`/`Referer` esperado; o portal usa `Referrer-Policy: origin`, que preserva somente a origem para essa validação sem vazar o token do caminho;
- cria cookie `HttpOnly`, `SameSite=Strict`;
- não é consumido por `GET` ou por link preview;
- é revogado após conclusão ou recuperação.

A Tool remove `portal_url` antes de montar o resultado para o LLM. A URL é entregue somente ao evento `execute` do frontend autenticado para montar o painel transitório; a Rich UI persistida não contém o token. O contexto retornado ao modelo contém apenas `WAITING_FOR_HUMAN` e a instrução para terminar o turno.

No modo local HTTP, o cookie não pode usar `Secure`/prefixo `__Host-`; o POC usa nome local distinto. Antes de qualquer publicação HTTPS, o broker muda automaticamente para cookie `__Host-...; Secure`.

O viewer:

- exige grant resgatado;
- exige cookie humano vinculado ao grant, usuário e epoch;
- verifica `Origin` no WebSocket;
- passa noVNC e o protocolo RFB pelo broker;
- entrega a senha RFB efêmera automaticamente no fragmento `#` do iframe (não enviado em HTTP/Referer), sem mostrá-la ao usuário ou ao modelo;
- não publica portas VNC/noVNC no host;
- desabilita clipboard nos dois sentidos;
- encerra x11vnc e websockify na devolução.

---

## 7. Browser e rede

O Chromium roda sem `--no-sandbox`. O container usa:

- usuário não root `cptr`;
- `cap_drop: ALL`;
- `no-new-privileges`;
- seccomp validado para Chromium sandbox;
- limite de 768 processos;
- 8 GiB de memória;
- 4 CPUs;
- 1 GiB de `/dev/shm`;
- nenhum Docker socket, `$HOME` do Mac, Keychain ou `~/.ssh`.

Policies do Chromium desabilitam:

- Password Manager;
- autofill de endereço;
- autofill de cartão;
- Browser Sign-in;
- Sync;
- métricas;
- geolocalização e notificações por padrão;
- esquemas locais como `file:`, `filesystem:`, `chrome:` e `devtools:` (o CDP loopback privado necessário ao agente permanece habilitado);
- QUIC e UDP WebRTC não proxy, reduzindo caminhos de bypass do proxy HTTP.

O proxy de saída aceita apenas HTTP/HTTPS nas portas 80/443 e rejeita:

- `localhost` e `*.localhost`;
- `host.docker.internal`;
- `*.local`;
- loopback IPv4/IPv6;
- RFC1918;
- IPv6 ULA;
- link-local;
- `169.254.169.254` e demais endereços não globais;
- DNS que resolva para qualquer endereço não global;
- portas como SSH, banco de dados ou APIs internas.

Isso é um controle do POC, não um firewall corporativo completo.

---

## 8. Código e arquivos operacionais

Fonte versionável:

```text
examples/browser-hitl-poc/
├── browser_hitl/
│   ├── api.py
│   ├── egress_proxy.py
│   ├── runtime.py
│   ├── security.py
│   ├── settings.py
│   └── store.py
├── openwebui/browser_hitl_tool.py
├── tests/
├── Dockerfile
├── compose.yaml
├── chromium-policy.json
├── provision_poc.py
├── pyproject.toml
└── .gitignore
```

Segredos locais, ignorados por Git:

```text
examples/browser-hitl-poc/secrets/
├── tool-api-key
├── admin-api-key
└── portal-signing-key
```

Todos estão em modo `0600`. O provisionador não passa valores em `argv`, labels, variáveis Docker ou logs.

Open WebUI foi alterado para:

```text
ENABLE_PLUGINS=true
ENABLE_VALVE_ENCRYPTION=true
ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS=false
ENABLE_CONTEXT_COMPACTION=true
CONTEXT_COMPACTION_MODEL=local.qwen38-omlx
CONTEXT_COMPACTION_TOKEN_THRESHOLD=245760
CONTEXT_COMPACTION_TOKEN_CAP=245760
CONTEXT_COMPACTION_RETENTION_PERCENTAGE=40
SAFE_MODE=true
```

As permissões persistidas de usuários comuns continuam:

```text
workspace.tools=false
workspace.tools_import=false
workspace.tools_export=false
sharing.tools=false
sharing.public_tools=false
```

Portanto, habilitar o runtime de Tools não concede criação/importação arbitrária aos usuários comuns. Ainda assim, Tools Python são execução de código no processo do Open WebUI; somente o administrador deve cadastrar código revisado.

Como traces de navegação podem crescer rapidamente, a compactação automática permanece ativa. O checkpoint declara máximo nativo de `262144` tokens e o oMLX anuncia o mesmo valor; o threshold/cap estimado de `245760` fornece margem nominal de `16384`, não uma reserva rígida. A fachada limita a saída a `8192`, vincula o teto reduzido à requisição antes do streaming e garante `prompt + output <= 262144`; o MTP também reduz a especulação junto ao limite usando os offsets reais dos caches. Como Tools são injetadas depois da decisão de compactação, schemas excepcionalmente grandes podem consumir a margem, reduzir a saída ou causar rejeição — não antecipar a compactação. A configuração está no `env`, no Config persistido e em `compact_token_threshold` do workspace model. Antes da ampliação, o chat que atingiu `34083` tokens foi compactado para um checkpoint de `1024` caracteres, mantendo suas dez mensagens visíveis; o contexto ativo estimado caiu de `29533` para `260` tokens.

---

## 9. Operação

### Estado

```bash
cd examples/browser-hitl-poc
docker compose ps
docker logs --tail=100 openwebui-browser-hitl-poc
curl -fsS http://127.0.0.1:3210/health
```

### Abertura do takeover fora do sandbox

O Open WebUI `0.11.0` renderiza Rich UI em iframe sandboxado. Um link `target="_blank"` dentro desse iframe abre uma aba que herda o sandbox; no Chromium isso bloqueou o portal local com `ERR_BLOCKED_BY_RESPONSE`.

A solução final não altera o frontend global nem afrouxa outros embeds. A Tool auditada emite o evento oficial `execute` para criar um painel transitório no contexto principal do Open WebUI. O painel:

- contém somente texto fixo, o motivo limitado e a URL efêmera retornada pelo broker;
- constrói os elementos com `createElement`/`textContent`, sem `innerHTML` ou `eval`;
- usa um link `target="_blank"` com `rel="noopener noreferrer"`;
- abre a aba por clique humano real, sem sandbox herdado;
- desaparece ao recarregar/navegar, enquanto a Rich UI persistida continua registrando que o takeover foi solicitado;
- não devolve a URL para o modelo.

A instalação anterior de patch em `frontend/index.html` foi removida; o arquivo global do Open WebUI permanece original.

### Reprovisionamento idempotente

```bash
cd examples/browser-hitl-poc
./provision_poc.py \
  --user '<UUID_RENATO>' \
  --user '<UUID_GIOVANNA>'
```

O comando:

1. cria/reutiliza segredos locais;
2. valida o Compose;
3. sobe o broker;
4. provisiona/reutiliza os perfis;
5. cria/atualiza a Tool;
6. grava as Valves cifradas;
7. reaplica os grants exatos.

### Parar sem apagar perfis

```bash
cd examples/browser-hitl-poc
docker compose stop
```

### Reiniciar

```bash
cd examples/browser-hitl-poc
docker compose start
```

O POC usa `restart: "no"` e não inicia automaticamente. Isso é intencional até completar o teste real e a revisão de segurança. O Compose possui healthcheck local do broker, mas uma queda ainda exige ação manual nesta fase.

### Rollback

Para retirar a capacidade sem apagar os perfis:

1. remover ou revogar a Tool `browser_hitl_private` no Open WebUI;
2. executar `docker compose stop`;
3. opcionalmente restaurar `ENABLE_PLUGINS=false` e reiniciar o Open WebUI.

Não remova o volume enquanto houver intenção de manter logins.

---

## 10. Como testar no Open WebUI

1. Entre como admin ou user-a.
2. Abra um chat com um modelo que suporte tool calling nativo.
3. No botão `+`/Tools, habilite **Navegador privado com login humano**.
4. Comece com:

```text
Abra https://example.com no meu navegador privado e diga o título da página.
```

5. Depois use uma conta de teste em um site de baixo impacto:

```text
Abra a página de login da minha conta de teste. Quando precisar de credenciais, pare e me entregue o navegador.
```

6. O agente mostra uma Rich UI explicativa e um painel verde transitório no canto da página.
7. No painel, clique em **Assumir navegador** no próprio Mac.
8. Faça o passo humano e clique em **Concluir e devolver ao agente**.
9. Volte ao chat e diga `continue`.
10. O agente deve chamar `browser_status`, encontrar `READY_TO_RESUME`, chamar `browser_resume` e continuar.

Não escreva senha, MFA ou CAPTCHA no chat.

---

## 11. Evidências de validação

A suíte automatizada passou com **48 testes** (o gate do Docker roda como o mesmo usuário não root `cptr` do runtime), cobrindo:

- IDOR entre usuários;
- state machine e epochs;
- reabertura de sessão sem sobrescrever a URL real da aba;
- lock do agente;
- hash de token;
- vinte resgates concorrentes com exatamente um vencedor;
- expiração de link não resgatado para `READY_TO_RESUME`;
- takeover já resgatado completável mesmo após o prazo inicial do link;
- recuperação fail-closed;
- `READY_TO_RESUME` preservado se o runtime falhar antes da nova lease;
- limpeza segura de locks/sockets Xvfb stale sem remover display ativo;
- slots únicos;
- cookie e CSRF vinculados ao grant, incluindo policy `origin` compatível com POST real do Chromium;
- bloqueio de destinos privados e portas não web;
- policies contra esquemas locais, QUIC e UDP WebRTC não proxy, preservando o CDP loopback do agente;
- painel `execute` restrito à Tool, URL ausente da Rich UI/model context e encoding seguro do motivo;
- migração explícita e unicidade do mapeamento de e-mail Access;
- assinatura, issuer, AUD, tempo, `type=app`, e-mail e `sub` do JWT;
- bloqueio cross-owner e isolamento de paths no hostname público;
- URL sem token após resgate, cookie ligado ao `sub` e headers noVNC em allowlist;
- prazo absoluto da intervenção, reconciliação fail-closed e revogação em troca de identidade;
- rollback de takeover ativo, um WebSocket por sessão e limites de frame.

O build Docker executa a suíte como gate e também passou.

O teste real local validou:

```text
navigate(example.com) → title "Example Domain"
request takeover      → WAITING_FOR_HUMAN
agent snapshot        → HTTP 423
clique real no portal → POST com Referer somente de origem; HUMAN_ACTIVE
noVNC HTML proxy      → PASS
noVNC browser real    → autenticação RFB automática e estado connected PASS
clique real concluir  → READY_TO_RESUME
resume                → AGENT_ACTIVE com nova epoch
```

Também foram validados:

- recuperação real de dois perfis após `SIGKILL`: um em `HUMAN_ACTIVE` e outro em `WAITING_FOR_HUMAN`, ambos para `READY_TO_RESUME`, runtime funcional e nova lease;
- duas pastas de perfil distintas em modo `0700` e artefatos/logs runtime em `0600`;
- VNC/websockify ausentes depois da devolução;
- Chromium sem `--no-sandbox`;
- tentativa ao vivo de `file:///etc/passwd` e `file:///run/secrets/tool-api-key` bloqueada por policy, com CDP do agente ainda funcional;
- flags ao vivo contra QUIC e UDP WebRTC não proxy;
- somente `127.0.0.1:3210` publicado;
- chave ausente de `docker inspect`, logs e process snapshot;
- `ENABLE_VALVE_ENCRYPTION=true` efetivo; a chave da Tool foi rotacionada e a Valve está em ciphertext Fernet;
- painel `execute` aberto no contexto principal, clique humano sem sandbox herdado e portal/noVNC funcional, sem alterar outros iframes;
- chave antiga e chave atual ausentes de `webui.db`, WAL e SHM após checkpoint/VACUUM;
- nenhum backup cifrado existente contém a chave antiga, pois a Tool foi criada depois do backup mais recente;
- ACL positiva para admin/user-a e negativa para os demais.

---

## 12. Publicação móvel com Cloudflare Access

O portal foi publicado em `https://browser.seudominio.com` em 26/08/2026, com escopo separado do chat:

- `browser.seudominio.com`: aplicação Access **Browser HITL - OTP**, somente One-Time PIN, allowlist exata de admin e user-a e sessão de uma hora;
- `chat.seudominio.com`: continua sem Cloudflare Access/OTP, protegido apenas pelo login normal do Open WebUI; não existe aplicação Access correspondente a esse hostname;
- a rota `chat.seudominio.com → http://127.0.0.1:3000` não possui `originRequest.access`;
- a rota `browser.seudominio.com → http://127.0.0.1:3210` exige o AUD dedicado tanto no edge quanto em `cloudflared`.

O broker valida novamente o JWT no origin: assinatura RS256 pelo JWKS rotativo, issuer `https://seudominio.cloudflareaccess.com`, AUD exato, `type=app`, `iat`, `nbf`, `exp`, `sub` e e-mail. O e-mail validado deve coincidir com o mapeamento administrativo imutável `Open WebUI UUID ↔ access_email` e com o snapshot do grant.

Depois do resgate, o token inicial é invalidado e sai completamente da URL. Portal, noVNC e WebSocket passam a usar caminhos sem token (`/portal`, `/viewer/vnc.html` e `/viewer/websockify`), com cookie `__Host-browser_hitl; Secure; HttpOnly; SameSite=Strict; Path=/` também vinculado ao `sub` do Access.

A intervenção humana tem prazo absoluto igual ao menor valor entre o `exp` do JWT e 3600 segundos. Ao expirar, o broker fecha o WebSocket/viewer, revoga o grant e move a sessão para `READY_TO_RESUME`; nunca devolve controle automaticamente ao agente. Há retry do timer e reconciliação pelo `browser_status`.

O hostname público expõe somente `/takeover/*`, `/portal`, `/portal/complete` e `/viewer/*`. `/tool/*`, `/admin/*`, `/health` e demais caminhos retornam `404` no host público, embora continuem disponíveis no loopback. O viewer aceita apenas assets GET, um WebSocket por sessão, frames de até 16 MiB e allowlists estritas de headers.

### Teste móvel pendente

A implantação e a reauditoria deram **GO somente para um primeiro teste de baixo risco**. Ainda falta validar manualmente no celular:

1. iniciar takeover em um site descartável ou `example.com`;
2. confirmar que a nova aba abre `browser.seudominio.com`, não `127.0.0.1`;
3. informar o e-mail na página Cloudflare Access;
4. receber e digitar o One-Time PIN **na página Access, nunca no chat**;
5. assumir o noVNC, interagir e concluir;
6. voltar ao chat, executar `browser_status`/`browser_resume` e confirmar nova epoch;
7. repetir uma vez com user-a para validar isolamento entre usuários.

Não use ainda Gmail principal, saúde, banco, governo ou administração de produção. Depois do E2E de baixo risco, ainda pendem:

1. política de backup cifrado separada para perfis, ou decisão explícita de não respaldá-los;
2. deprovisionamento e exclusão definitiva de perfil;
3. LaunchAgent/autostart somente após aprovação;
4. teste simultâneo com duas pessoas.

Riscos residuais:

- após o login, o agente age com os privilégios da conta autenticada;
- conteúdo de e-mail/documentos pode conter prompt injection;
- Google, Meta ou LinkedIn podem detectar e bloquear automação;
- passkeys/Touch ID/chaves USB podem não funcionar no viewer Linux remoto;
- administrador do Mac/Open WebUI continua tecnicamente capaz de acessar os perfis;
- o proxy de egress do POC não substitui uma política de rede em camada inferior.

Ações irreversíveis ou de alto impacto devem exigir confirmação humana separada: enviar e-mail, publicar conteúdo, compartilhar arquivos, mudar permissões, excluir dados, comprar ou alterar segurança da conta.

---

## 13. Referências

- Open WebUI Tools: <https://docs.openwebui.com/features/extensibility/plugin/tools/development/>
- Open WebUI Rich UI: <https://docs.openwebui.com/features/extensibility/plugin/development/rich-ui/>
- Open WebUI reserved arguments: <https://docs.openwebui.com/features/extensibility/plugin/development/reserved-args/>
- OpenBrowser avaliado: <https://github.com/floomhq/openbrowser>
- Open WebUI Computer: <https://github.com/open-webui/computer>

---

## Conclusão

O POC prova localmente o requisito central: **admin e user-a podem ter perfis persistentes e isolados; o agente e o humano compartilham a mesma sessão/aba; e o broker impede controle ou observação concorrente do agente durante login humano**.

O próximo passo seguro não é testar imediatamente a conta Google principal. A autenticação remota do portal já foi implantada com Cloudflare Access/OTP; falta executar o primeiro E2E móvel com `example.com` e depois uma conta de baixo valor, validar a experiência e o isolamento dos dois usuários e somente então considerar contas mais sensíveis.
