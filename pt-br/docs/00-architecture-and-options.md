# Instalação local-first: arquitetura e opções

> [English](../../docs/00-architecture-and-options.md) · **Português**

> Para o navegador universal multiusuário com login humano, consulte [`04-browser-hitl-multi-user-poc.md`](04-browser-hitl-multi-user-poc.md). O POC publicado é uma camada separada e não altera a escolha de hospedagem descrita abaixo.

**Data de referência:** 27 de agosto de 2026  
**Domínio:** `seudominio.com`  
**Status:** índice arquitetural; o cenário sem VPS registra a implantação atual, enquanto o cenário com VPS permanece um runbook não executado

O objetivo deste guia é **instalar, configurar e usar um modelo local com o Open WebUI**, tudo em um
único Mac. Este arquivo é o índice: fixa a arquitetura local e a escolha do modelo, e marca o ramo
com VPS como opcional. Os procedimentos completos permanecem separados.

Nada aqui exige VPS. O único requisito que a justificaria é manter o WebUI no ar com o Mac desligado
— se isso não importa para você, leia [`02-deploy-macos-cloudflare-tunnel.md`](02-deploy-macos-cloudflare-tunnel.md) e pule [`03-deploy-with-vps.md`](03-deploy-with-vps.md).

---

## Escolha do modelo local

Para uma **nova instalação reproduzível** num M3 Max de 40 núcleos GPU e 128 GB, use:

- [`05-cleanroom-install.md`](05-cleanroom-install.md) — visão geral;
- [`../examples/qwen38-official-omlx/README.md`](../../examples/qwen38-official-omlx/README.md) — guia executável e bundle.

Esse caminho baixa `fcmeyer/Qwen3.8-27B-MLX-oQ4e-mtp@0299356…`, uma quantização comunitária fixada que declara o modelo oficial `Qwen/Qwen3.8-27B` como base. Não há requantização local.

O arquivo [`01-case-study-qwen38-m3-max.md`](01-case-study-qwen38-m3-max.md) continua sendo o **registro histórico** do checkpoint uncensored `pyros-vault/...`. Seus benchmarks de 46–50 tok/s e canários 256K não devem ser atribuídos ao checkpoint `fcmeyer` sem uma nova medição.

---

## Opção 1 — sem VPS (padrão)

Use:

- [`02-deploy-macos-cloudflare-tunnel.md`](02-deploy-macos-cloudflare-tunnel.md)

Arquitetura:

```text
Celular → Cloudflare Tunnel → Login do Open WebUI no Mac
                             ├→ Qwen no próprio Mac
                             └→ OpenRouter opcional
```

Características:

- Open WebUI roda nativamente no macOS;
- WebUI público em `https://chat.seudominio.com`;
- Qwen acessado somente por `http://127.0.0.1:8084/v1`;
- não existe `llm-home.seudominio.com`;
- nenhuma VPS e nenhum Service Token;
- dados e histórico permanecem no Mac;
- instalação mais simples; a tela de login é pública, sem Cloudflare Access/OTP, por decisão do proprietário;
- signup está fechado e o login tem rate limiting Cloudflare;
- se o Mac desligar, WebUI, Qwen e o acesso ao OpenRouter por essa interface ficam offline.

Escolha esta opção se simplicidade e armazenamento local forem mais importantes que disponibilidade contínua.

---

## Opção 2 — com VPS (opcional)

Use:

- [`03-deploy-with-vps.md`](03-deploy-with-vps.md)

Arquitetura:

```text
                         ┌→ OpenRouter
Celular → Open WebUI VPS ┤
                         └→ Cloudflare Access/Tunnel → Qwen no Mac
```

Características:

- Open WebUI e histórico rodam numa VPS;
- WebUI público em `https://chat.seudominio.com`;
- Qwen publicado como API mínima em `https://llm-home.seudominio.com/v1`;
- Service Auth da Cloudflare + Bearer do Qwen;
- OpenRouter continua disponível quando o Mac estiver desligado;
- somente o Qwen local fica indisponível quando o Mac cai;
- mais componentes, segredos, custo e superfície operacional;
- prompts passam pela VPS/Cloudflare e o histórico fica armazenado na VPS.

Escolha esta opção se o requisito principal for usar o WebUI e OpenRouter mesmo sem o Mac.

Lembre que este ramo ainda não foi executado: o runbook está completo, mas não verificado contra uma
VPS real. Se você começa hoje, o caminho local é o que tem evidência por trás.

---

## Comparação direta

| Critério | Sem VPS | Com VPS |
|---|---|---|
| WebUI quando Mac está desligado | **offline** | **online** |
| OpenRouter quando Mac está desligado | offline por essa UI | **online** |
| Qwen quando Mac está desligado | offline | offline |
| Histórico | Mac | VPS |
| API Qwen com hostname público | não | `llm-home.seudominio.com`, protegida |
| Service Token | não | sim |
| Complexidade | menor | maior |
| Custo mensal de compute cloud | nenhum | VPS |
| Privacidade operacional | dados ficam no Mac; login fica público | menor; VPS vê os dados em claro |
| Backup | Mac + cópia externa | VPS + storage externo |
| Melhor para | uso pessoal ligado ao Mac | disponibilidade contínua |

---

## Hostnames reservados

| Hostname | Sem VPS | Com VPS |
|---|---|---|
| `chat.seudominio.com` | Tunnel até Open WebUI no Mac | Tunnel até Open WebUI na VPS |
| `llm-home.seudominio.com` | **não criar** | Tunnel até API mínima do Qwen no Mac |
| `seudominio.com` / `www.seudominio.com` | livres | livres |

Não implante os dois runbooks simultaneamente usando o mesmo `chat.seudominio.com`: uma rota DNS/Tunnel só pode representar a origem escolhida. Para testar as arquiteturas em paralelo, use hostnames distintos e Access applications separadas, por exemplo `chat-local.seudominio.com` e `chat-vps.seudominio.com`, removendo-os depois da decisão.

---

## Recomendação

**Padrão: sem VPS.** Ele cumpre o objetivo — instalar, configurar e usar um modelo local com o Open
WebUI — com menos peças móveis, sem custo de cloud e com os dados sem sair do Mac.

Escolha **com VPS** só se um requisito específico se aplicar: o WebUI e o OpenRouter precisarem
continuar acessíveis com o Mac desligado. Todo o resto da instalação local permanece igual.

**Cloudflare Tunnel não hospeda o Open WebUI.** Ele transporta tráfego até uma origem ativa e, portanto, não muda essa distinção.
