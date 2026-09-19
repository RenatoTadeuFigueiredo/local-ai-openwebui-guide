# Adicionar um segundo modelo local sem tocar no primeiro

> [English](../../docs/06-second-local-model.md) · **Português**

**Data de referência:** 16 de setembro de 2026  
**Status:** executado e validado de ponta a ponta na máquina de referência (instalação, verificador completo, canário de contexto longo, ligação com o Open WebUI); benchmarks de qualidade e comportamento de longa duração/térmico não medidos  
**Pré-requisito:** [`02-deploy-macos-cloudflare-tunnel.md`](02-deploy-macos-cloudflare-tunnel.md) já concluído — o primeiro perfil está rodando

O primeiro perfil serve um modelo 27B com contexto de 256K. Este documento adiciona um **segundo modelo, menor,
ao lado dele**, sem reconfigurar nada que já funciona.

O exemplo executável é [`../examples/ornith15-omlx/`](../examples/ornith15-omlx/README.md) —
Ornith-1.5-9B, um 9B agêntico/de código com MTP nativo, servido como perfil isolado. O raciocínio
vale para qualquer outro checkpoint.

---

## O que "ao lado" significa, na prática

Um segundo perfil é uma cópia do mesmo padrão endurecido com identidade própria. Nada é compartilhado:

| Recurso | Primeiro perfil | Segundo perfil |
|---|---|---|
| Diretório | `~/models/qwen38-omlx` | `~/models/ornith15-omlx` |
| Porta | `8084` | `8086` |
| ID do modelo | `qwen38-omlx` | `ornith15-omlx` |
| Verificador | fixa o checkpoint 27B | fixa o checkpoint 9B |
| LaunchAgent | `com.local.qwen-omlx` | `com.local.ornith-omlx` |
| Controlador | `qwen-omlx` | `ornith15-omlx` |
| Prefixo do Open WebUI | `local.` | `ornith.` |

O custo é disco e mais um serviço para supervisionar. O benefício é que um checkpoint ruim, uma mudança
de template ou uma regressão do oMLX no segundo perfil não conseguem derrubar o primeiro — e cada perfil
mantém seu próprio verificador, que é o que torna a garantia verificável em vez de aspiracional.

> **Opcional**. `8085` parece a próxima porta óbvia e é frequentemente ocupada por Docker numa máquina
> de desenvolvedor. Confira antes de decidir: `lsof -nP -iTCP:8086 -sTCP:LISTEN`.

---

## Escolha do checkpoint

Três perguntas decidem, nesta ordem:

1. **O runtime suporta a arquitetura?** oMLX `0.6.3rc1` cobre a família `qwen3_5`,
   incluindo o caminho do drafter MTP. Um modelo fora das famílias suportadas precisa de outro runtime,
   não de outro perfil.
2. **O checkpoint carrega a cabeça MTP?** MTP é o que torna um modelo pequeno utilizável a 60+ tok/s
   aqui. Verifique o index, não o model card:
   `python3 -c "import json;print(len([k for k in json.load(open('model/model.safetensors.index.json'))['weight_map'] if k.startswith('language_model.mtp.')]))"`.
   Zero significa sem decodificação especulativa, diga o nome o que disser.
3. **Está fixado e verificável?** Uma revisão que você consegue nomear, um conjunto de arquivos que você
   consegue hashear, uma quantização que você consegue descrever.

A questão do FP8 ilustra bem as três: o runtime suporta FP8, mas nenhum bundle Ornith publicado combina
FP8 com uma cabeça MTP funcional — e um deles esconde a cabeça num arquivo sidecar que o oMLX nunca lê.
O levantamento completo está no [README do exemplo](../examples/ornith15-omlx/README.md).

---

## Procedimento

```bash
cd examples/ornith15-omlx
./install.sh                                  # pinned wheel + pinned checkpoint + full verifier
./ornith15-omlx start                         # verifier, sandbox, wait for load
./context-canary.py                           # long-context retrieval evidence
./wire-open-webui.py                          # connection, model row, wildcard read grant
launchctl kickstart -k gui/$(id -u)/com.local.openwebui   # exige o job carregado: o `local-ai up` faz isso
```

Depois confirme que o modelo aparece e responde pela interface — uma conexão que nunca foi exercitada
de ponta a ponta não é uma conexão que funciona.

### Opcional: ligar no Grok CLI

A mesma facade é um endpoint OpenAI-compatible comum, então a TUI pode usá-la direto. Adicione um
provider por perfil e uma entrada de modelo apontando para ele, em `~/.grok-prod/config.toml`:

```toml
[model_providers.local-ornith]
kind = "openai_compatible"
display_name = "local oMLX (Ornith 1.5 9B)"
base_url = "http://127.0.0.1:8086/v1"
api_key = "<conteudo de state/api-key>"
api_backend = "chat_completions"
auth_scheme = "bearer"
catalog_enabled = false

[model."local/ornith15-omlx"]
model = "ornith15-omlx"
model_provider = "local-ornith"
name = "Ornith 1.5 9B (local)"
api_key = "<conteudo de state/api-key>"
max_completion_tokens = 8192     # a facade limita a saída a isso
context_window = 262144          # nativo, e o que a facade impõe
supports_tools = true
stream_tool_calls = true
```

`catalog_enabled = false` importa: a facade não expõe rotas de gestão de modelos, só inferência, então
não há nada para descobrir. Os dois perfis usam a mesma forma, com porta e chave próprias.

### Medido na máquina de referência

| | |
|---|---|
| Carregamento do modelo | 5,41 GB reais |
| Decodificação com MTP | média de 67,3 tok/s na sessão, 50–60 % de aceitação |
| Prompt de 109.137 tokens | needle recuperado, ~397 tok/s de prefill |
| Prompt acima do limite (363.340 tokens) | rejeitado com um 400 claro, não truncado em silêncio |
| Chamadas de ferramenta e `reasoning_content` | ambos funcionam pela fachada |

---

## O que isto não entrega

- **Números de qualidade.** Nada aqui diz que o 9B é bom, apenas que roda corretamente e rápido.
- **Uma segunda cópia dos pesos.** Cada perfil armazena seu próprio modelo; não há blob store compartilhado.
- **Cache compartilhado.** O cache de prefixos no SSD é por perfil, então os dois não aquecem um ao outro.
- **Failover.** Os dois perfis são independentes; nenhum substitui o outro se um morrer.

---

## Pendente

- comparação de qualidade contra o perfil 27B nos mesmos prompts;
- estabilidade de longa duração e comportamento térmico sob decodificação sustentada;
- ~~decisão sobre se ambos os perfis devem ter autostart, ou o menor sob demanda~~ — decidido por
  demanda para os dois: veja [`examples/local-ai-control/`](../examples/local-ai-control/);
- visão: o checkpoint inclui tensores de visão, o perfil força o engine de texto;
- backup: o backup cifrado cobre apenas o primeiro perfil. O segundo modelo é re-baixável a partir de
  uma revisão fixada, mas seu `state/` (API key, settings, settings por modelo) ainda não é copiado —
  um restore regeraria a chave e quebraria a conexão com o Open WebUI.