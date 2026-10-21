# 10. Rotear clientes locais (Grok Build, dsh)

> **Português** · [English](../docs/10-local-clients.md)

Dois clientes desta máquina conseguem falar com o perfil local em vez de um provedor de nuvem:
Grok Build e `dsh` / `dsh-tui`. Ambos usam a API de chat-completions da OpenAI, que a fachada já
implementa atrás da chave bearer do perfil.

Os trechos ficam em [`examples/local-client-routes/`](../../examples/local-client-routes/); esta
página cobre as peças móveis e os modos de falha.

## Grok Build

Anexe o bloco de provedor de
[`grok-provider.toml`](../../examples/local-client-routes/grok-provider.toml) ao `$GROK_HOME/config.toml`
ativo, substitua a chave, reinicie e use `/model` para `local/sage-a15-omlx` ou `local/qwen38-omlx`.

As capacidades importam. O template do perfil controla raciocínio por `enable_thinking`, não por
`reasoning_effort`, então a rota declara `supports_reasoning_effort = false`; deixar ligado faz o
cliente enviar um botão que o template ignora. `supports_image_input` só é verdadeiro no alias
Sage, que traz torre de visão.

## dsh / dsh-tui

O `dsh` compõe camadas em ordem: bundles, patch do perfil e, por último, a camada de casa em
`~/.dsh/cordis.patch.yml`. Tanto o perfil distribuído quanto a camada de casa alteram `llm-pi-ai`,
e um patch substitui o bloco de config inteiro — por isso o provedor vai na camada de **casa**.
Colocá-lo no patch do perfil funciona até a próxima atualização de bundle compor por cima.

```bash
# 1. mescle examples/local-client-routes/dsh-provider.yml em ~/.dsh/cordis.patch.yml
# 2. chave, fora do YAML
printf 'OMLX_LOCAL_KEY=%s\n' "$(cat ~/models/<perfil>/state/api-key)" >> ~/.dsh/.env
# 3. prove que compõe
dsh --profile dsh-tui --dump-config | sed -n '/- id: llm-pi-ai/,/^- id: /p'
# 4. resposta pontual no modelo local, sem tocar nos padrões
dsh --profile headless --patch /tmp/pick-local.yml "reply with exactly: ok"
```

`apiKeyEnv` resolve pelo cofre de credenciais, pelo ambiente de lançamento e por fim
`~/.dsh/.env` — a chave nunca entra em arquivo versionado.

## Por que os manifestos carregam timeout e contexto

- `request_timeout_secs = 600` / `timeoutMs = 900000`: prefill frio de system prompt de tamanho
  agente leva minutos, não segundos. Cliente que desiste em 60 s reporta servidor saudável como
  quebrado.
- `context_window = 262144`: nativo para os dois checkpoints. Declarar menos trunca em silêncio;
  declarar mais faz o servidor recusar a cauda.
- `max_completion_tokens = 8192`: casa com o teto de saída do perfil. Valores maiores não estendem
  a resposta, o servidor corta no próprio teto.

## Modos de falha

| Sintoma | Causa | Correção |
|---|---|---|
| Modelo ausente no seletor | bloco na camada errada, ou `enabled = false` | camada de casa, `enabled = true`, reiniciar o cliente |
| 401 em toda requisição | chave rotacionada | reler `state/api-key` para a config |
| 400 com mensagem da guarda de memória | dois modelos residentes e tier `safe` | definir `memory_guard_tier: balanced` |
| Requisições travam e falham | timeout do cliente abaixo do prefill | aumentar o timeout no bloco do provedor |
| Segundo cliente emperra | `max_concurrent_requests: 1` | esperado; ele entra na fila |

## Notas de convivência

Os dois clientes compartilham uma fachada e uma chave. O `idle_timeout_seconds: 600` do perfil
descarrega o modelo após dez minutos ocioso, custando recarga na chamada seguinte; a primeira
requisição depois disso é lenta por desenho, não por defeito.
