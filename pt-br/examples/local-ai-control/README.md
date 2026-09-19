# Stack de IA local sob demanda — `local-ai up`, `local-ai down`

> [English](../../../examples/local-ai-control/README.md) · **Português**

**Data de referência:** 19 de setembro de 2026  
**Hardware medido:** MacBook Pro com Apple M3 Max, GPU de 40 núcleos e 128 GB de memória unificada  
**Sistema/runtime:** macOS 15 ou mais recente, domínio de usuário do `launchd`

A stack implantada subia no login: três LaunchAgents em `~/Library/LaunchAgents/` segurando um modelo
de 27B, um de 9B, o Open WebUI e um Túnel. Funcionava — e significava ~21 GB de memória unificada mais
os processos do WebUI e do Túnel residentes de login a logout, com ou sem alguém conversando. Este
bundle mantém o `launchd` como supervisor e move o gatilho para um comando:

```bash
local-ai up      # modelos, WebUI e o que mais você pedir
local-ai down    # não deixa nada para trás
```

---

## 1. Por que funciona

O `launchd` carrega exatamente um diretório de usuário no login: `~/Library/LaunchAgents/`. Um plist
em qualquer outro lugar fica inerte até alguém fazer `bootstrap` nele. É todo o truque — os plists vão
para `~/.config/local-ai/agents/`, e o `local-ai` chama `launchctl bootstrap` e `launchctl bootout`.

Nada mais muda. Enquanto uma unidade roda, o `launchd` continua dono dela: `RunAtLoad`, `KeepAlive`,
`ThrottleInterval`, `WorkingDirectory` e o redirecionamento de stdout/stderr vêm todos do plist, então
um WebUI que quebra continua sendo reiniciado e os logs continuam caindo onde sempre caíram. E o
`bootout` — não o `kill` — é o interruptor de desligar, que é o que faz o "desligado" durar: o
`KeepAlive` não ressuscita um job removido do domínio.

Não há daemon nem polling. O `local-ai` é um script bash que lê sinais de saúde e termina.

---

## 2. Instalação

```bash
chmod +x local-ai
ln -sfn "$PWD/local-ai" ~/.local/bin/local-ai        # ~/.local/bin está no PATH; a cópia do repo fica viva
mkdir -p ~/.config/local-ai/agents
for f in agents/*.plist.template; do
  sed "s|__HOME__|$HOME|g" "$f" > ~/.config/local-ai/agents/"$(basename "$f" .template)"
done
plutil -lint ~/.config/local-ai/agents/*.plist
```

Se a stack já estava rodando a partir do local antigo, no login, descarregue uma vez para os dois
arranjos não se sobreporem:

```bash
for l in com.local.ornith-omlx com.local.qwen-omlx com.local.openwebui \
         com.local.cloudflared-openwebui com.local.docker-desktop-openwebui com.mlx-server; do
  launchctl bootout "gui/$(id -u)/$l" 2>/dev/null
done
```

`LOCAL_AI_AGENTS_DIR` sobrescreve o diretório dos plists se você os mantiver em outro lugar.

---

## 3. Comandos

```bash
local-ai up [--tunnel] [--docker] [--legacy] [--all] [--open]
local-ai down [--docker]
local-ai restart [flags]
local-ai status
local-ai logs <unit>
```

| Comando | Efeito |
|---|---|
| `up` | Ornith (`8086`), Qwen (`8084`), Open WebUI (`3000`) |
| `up --tunnel` | Soma o Túnel Cloudflare — `chat.seudominio.com` volta a responder |
| `up --docker` | Soma o Docker Desktop, exigido pelos containers opcionais de terminal/Computer |
| `up --legacy` | Soma o antigo servidor mlx-lm na `8080` |
| `up --all` | As três unidades opcionais acima, juntas |
| `up --open` | Abre o WebUI no navegador quando ele responde |
| `down` | Para toda unidade gerenciada que estiver rodando; deixa o Docker Desktop quieto |
| `down --docker` | Também encerra o Docker Desktop |
| `status` | Unidade, estado no `launchd`, pid, porta, saúde e memória residente |

O `up` é idempotente (`already up`) e ordenado: modelos primeiro, depois Open WebUI, depois o Túnel,
cada um aguardado pelo próprio sinal de saúde. Uma unidade que nunca fica saudável é nomeada, o `up`
sai com código não-zero e `local-ai logs <unit>` mostra o porquê.

O `down` também é idempotente (`nothing was running`) e reporta qualquer processo que não conseguiu
parar em vez de declarar sucesso.

---

## 4. As unidades

| Unidade | Label | Porta | Sinal de saúde |
|---|---|---|---|
| `ornith` | `com.local.ornith-omlx` | `8086` | `/health` + modelo presente em `/api/status` |
| `qwen` | `com.local.qwen-omlx` | `8084` | idem |
| `openwebui` | `com.local.openwebui` | `3000` | `/health` |
| `tunnel` | `com.local.cloudflared-openwebui` | `20241` | `/ready` do túnel |
| `docker` | `com.local.docker-desktop-openwebui` | — | `docker info` |
| `legacy` | `com.mlx-server` | `8080` | `/v1/models` |

As unidades de modelo conferem se o modelo *certo* está carregado, não só se a porta responde: um
perfil que subiu com o engine pool vazio não é reportado como pronto.

---

## 5. Medições

Na máquina de referência, depois da mudança:

| Operação | Resultado |
|---|---|
| `down` (5 unidades) | 3,6 s, portas `3000`, `8084`, `8086`, `20241`, `8080` liberadas |
| `up` (frio, page cache quente) | 55 s no total — 4 s Ornith, 5 s Qwen, 31 s Open WebUI, < 1 s Túnel |
| `down --docker` | 18 s, Docker Desktop encerrado, seus 8 containers parados |
| Memória liberada pelo `down` | ~21 GB residentes (Qwen 15,5 GB, Ornith 5,5 GB, WebUI 0,7 GB) mais a VM do Docker |
| Chat pela URL pública após um ciclo completo de `down`/`up` | respondeu (`E2E-OK`) |

O Túnel reconecta no próximo `up --tunnel` com um novo connector id; nada é recriado na Cloudflare.

---

## 6. Limites honestos

- **O Docker Desktop é compartilhado.** Um `down` puro o deixa rodando porque outros projetos desta
  máquina mantêm containers nele. Encerrá-lo para os containers deles também.
- **Os perfis de modelo não têm `KeepAlive`.** Uma quebra no meio da sessão não é reiniciada — isso já
  era verdade antes desta mudança. O WebUI e o Túnel têm.
- **Um job carregado do caminho antigo sobrevive até ser descarregado.** O laço da seção 2 resolve;
  depois dele, `local-ai status` deve mostrar `-` em `LAUNCHD` para tudo.
- **Unidade subida na mão é parada pelo controlador.** O `down` cai para `./ornith15-omlx stop` /
  `./qwen-omlx stop` quando o `launchd` nunca foi dono do processo, e reporta se isso também falhar.
- **Os plists guardam caminhos absolutos.** O `__HOME__` é expandido na instalação; os scripts
  apontados (`~/services/open-webui-mac/app/*.sh`) precisam existir.
- **`legacy` é a unidade mais fraca.** O sinal de prontidão é só `/v1/models`; não há verificador nem
  checkpoint fixado por trás dela, diferente dos dois perfis oMLX.
- **Nada aqui sobrevive a um reboot sozinho** — essa é a ideia, mas significa que uma máquina que
  reinicia de madrugada precisa de um `local-ai up` antes de o celular voltar a conversar.

---

## 7. Voltando ao autostart

Mova os plists de volta para `~/Library/LaunchAgents/`. Eles carregam `RunAtLoad` (e `KeepAlive` onde
importa), então sobem no próximo login exatamente como antes — e o `local-ai` continua funcionando por
cima, porque ele só faz `bootstrap` e `bootout` por label.