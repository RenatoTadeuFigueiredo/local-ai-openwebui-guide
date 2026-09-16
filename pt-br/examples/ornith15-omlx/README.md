# Ornith-1.5-9B no M3 Max — um segundo perfil oMLX isolado

> [English](../../../examples/ornith15-omlx/README.md) · **Português**

**Data de referência:** 16 de setembro de 2026  
**Hardware medido:** MacBook Pro com Apple M3 Max, GPU de 40 núcleos e 128 GB de memória unificada  
**Sistema/runtime:** macOS 15 ou mais recente, Python 3.12, oMLX `0.6.3rc1`  
**Modelo local:** `ornith15-omlx`  
**API:** `http://127.0.0.1:8086/v1`

Este bundle instala um **segundo modelo ao lado do perfil Qwen**, em diretório, porta e
verificador próprios. Nada no perfil existente muda. É a resposta executável a uma pergunta: *um
modelo 9B pode ser servido nesta stack com o mesmo isolamento, e com Lightning MTP?* Pode, com o
checkpoint abaixo.

```text
mlx-works/Ornith-1.5-9B-oQ4e-mtp
@ f6012213916a7df42640539c1df7cd031b2569fb
```

O checkpoint `mlx-works` é uma quantização de terceiro de `ornith-ai/Ornith-1.5-9B`, feita com a
ferramenta `oQ` que acompanha o próprio oMLX. Ele declara o repositório base mas **não fixa a revisão
base**, então equivalência tensor a tensor com o BF16 oficial não está provada — apenas a revisão
escolhida e seus arquivos são autenticados aqui.

---

## 1. Por que este checkpoint e não um FP8

FP8 é possível nesta stack: MLX `0.32.1` suporta `mxfp8` (group size 32, 8 bits), a ferramenta `oQ`
emite 8-bit como `mxfp8` e ingere fontes FP8, e o Lightning MTP do oMLX não está amarrado a um formato
de quantização — ele se baseia em tensores `mtp.*`, e outras famílias de modelo já rodam MTP sobre
pesos `oQ8e`/`mxfp8`.

O que **não** existe é um bundle Ornith publicado com FP8 **e** uma cabeça MTP funcional. Toda conversão
Ornith de 8 bits no Hub traz zero tensores `mtp.*` no index:

| Bundle | Payload | `mtp.*` no index | Nota |
|---|---|---|---|
| `ornith-ai/Ornith-1.5-9B-MLX-4bit` | 5,06 GB | 0 | MLX oficial do fornecedor, sem MTP |
| `mlx-works/Ornith-1.5-9B-oQ4e-mtp` | 6,25 GB | **29** | oQ misto 4/5-bit, usado aqui |
| `djrsystemservices/Ornith-1.5-9B-oQ6e-mtp` | 8,53 GB | **29** | variante oQ 6-bit |
| `scottlowry/Ornith-1.5-9B-oQ8e` | 10,45 GB | 0 | 8-bit, sem MTP |
| `OsaurusAI/Ornith-1.5-9B-MXFP8` | 10,17 GB | 0 | JANG, `bundle_has_mtp: false` |
| `Artie101/Ornith-1.5-9B-8bit-MTPLX` | 10,93 GB | 0 | MTP num sidecar `mtp.safetensors` |

Essa última linha importa: o oMLX decide se anexa a cabeça MTP lendo **apenas**
`model.safetensors.index.json` (`omlx/utils/model_loading.py`). Uma cabeça guardada num arquivo sidecar
fora do index é invisível, então o modelo decodifica em silêncio sem MTP.

Como a máquina é limitada por largura de banda de memória, 8-bit também custa cerca de 1,6× os bytes por
token do mix oQ4e — antes do ganho de ~30 % de decodificação que o MTP acrescenta por cima. O checkpoint
oQ4e vence nos dois eixos; FP8 só faria sentido aqui depois de quantizar localmente com `oQ --bits 8`,
o que este bundle não faz.

---

## 2. Resultado esperado

- um modelo oQ4e de precisão mista (base affine 4-bit g64, 72 tensores elevados para 5-bit) com 29
  tensores MTP embutidos, ~6,2 GB de payload;
- venv Python 3.12 isolado com oMLX `0.6.3rc1`;
- Lightning MTP habilitado, profundidade adaptativa de até 3 drafts;
- contexto nativo de `262144` tokens, saída limitada a `8192`, `prompt + saída <= contexto` imposto pela
  fachada;
- concorrência única, cache de prefixos de 40 GB no SSD, `HOME` privado, estado relativo ao `HOME`;
- seis rotas de inferência/estado atrás de Bearer, sem rotas admin/MCP/download;
- rede de saída negada por `sandbox-exec`.

### O que não está incluído

- requantização do BF16;
- visão. O checkpoint carrega `vision_config` e arquivos de processor, mas o perfil força o
  engine de texto (`model_type_override: llm`) exatamente como o perfil Qwen;
- YaRN / extensão para 1M;
- um gate de hardware tão estrito quanto o do perfil 27B — um 9B cabe em Macs menores, mas os números
  abaixo são de um M3 Max.

---

## 3. Resultados medidos

Registrados em 16 de setembro de 2026 no hardware de referência, com o perfil acima. Os números são deste
checkpoint e **não devem ser transferidos** para as conversões MLX do fornecedor.

| Medição | Resultado |
|---|---|
| Carregamento do modelo | 5,41 GB reais / 6,08 GB estimados |
| Decodificação com MTP, média da sessão | 67,3 tok/s |
| Aceitação MTP, prompts curtos | 50–60 %, profundidade d1–d3 |
| Prompt de 109.137 tokens, needle recuperado | sim, ~397 tok/s de prefill, 275 s de parede |
| Prompt de 363.340 tokens | rejeitado corretamente: `Prompt too long … exceeds max context window of 262144` |
| Chamada de ferramenta via `/v1/chat/completions` | `tool_calls` retornado, argumentos bem formados |
| Separação de thinking | `reasoning_content` preenchido, `content` limpo |
| Instalação limpa deste bundle | executada contra um target novo; verificador completo passou |

Não medidos: benchmarks de qualidade, estabilidade de longa duração, comportamento térmico, comparação
contra o perfil 27B.

---

## 4. Instalação

```bash
cd examples/ornith15-omlx
./install.sh                      # default target: ~/models/ornith15-omlx
```

O script confere macOS 15+, `python3.12`, git, disco livre, se a porta `8086` está livre e se o
LaunchAgent não está carregado; depois baixa o wheel e o checkpoint fixados, constrói o venv,
renderiza os arquivos de estado, cria o symlink do modelo e executa o verificador **completo**.

```bash
./install.sh --target /Volumes/fast/models/ornith15-omlx
./install.sh --skip-download      # restore over an existing model/
```

> **Opcional**. A porta padrão é `8086` porque `8085` costuma estar ocupada por Docker numa máquina de
> desenvolvedor (no caso medido, um container Kafka Connect). Se `8086` também estiver ocupada, altere
> `PORT` em `serve.sh`, `launchd-start.sh`, `ornith15-omlx` e `state/settings.json` juntos.

---

## 5. Verificação

```bash
./runtime/venv/bin/python verify-model.py          # full: wheel + shards SHA-256, metadata identities
./runtime/venv/bin/python verify-model.py --quick  # structural only
```

O verificador fixa: o digest do wheel oMLX, quatro versões do runtime instalado, a revisão do checkpoint,
o conjunto exato de arquivos com tamanhos, os SHA-256 dos dois shards, 16 identidades de metadados
Git-blob/LFS, `model_type`, o contexto nativo de 262144, parâmetros RoPE, os 29 tensores MTP, os 72
overrides de 5-bit elevados e a base de quantização. Ele também exercita os guards de contexto/saída e a
allowlist de rotas, e falha fechado se o sandbox, os secrets ou as configurações sofrerem drift.

---

## 6. Execução

```bash
./ornith15-omlx start
./ornith15-omlx status
./ornith15-omlx chat "explain the MTP head in one line"
./ornith15-omlx chat-fast "no thinking, just answer"
./ornith15-omlx stop
```

`start` roda o verificador, lança via `sandbox-exec` e espera até o modelo estar carregado antes de
retornar. O controlador só assume processos que consegue provar pertencerem a este perfil.

### Autostart

```bash
sed "s#__PROFILE_ROOT__#$PWD#g" com.local.ornith-omlx.plist.template \
  > ~/Library/LaunchAgents/com.local.ornith-omlx.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ornith-omlx.plist
```

### Canário de contexto longo

```bash
./context-canary.py     # writes context-canary-results.json
```

---

## 7. Ligação com o Open WebUI

`wire-open-webui.py` adiciona a conexão (`http://127.0.0.1:8086/v1`, prefixo `ornith`), uma linha de
modelo e uma concessão de leitura com wildcard, para que o modelo apareça para todo usuário. É
idempotente e exige reiniciar o Open WebUI depois.

```bash
./wire-open-webui.py
launchctl kickstart -k gui/$(id -u)/com.local.openwebui
```

O ID de modelo resultante é `ornith.ornith15-omlx`. O script assume o layout usado por este guia
(`~/services/open-webui-mac/data/webui.db`); ajuste `DB` se o seu for diferente.

---

## 8. Limites honestos

- A revisão base de `ornith-ai/Ornith-1.5-9B` não é fixada pelo conversor; o valor observado no nome do
  cache de calibração do oQ (`3a3ef0675603`) é contexto, não prova.
- O conversor substituiu o chat template por um template "fixed" da comunidade e manteve o upstream como
  `chat_template.jinja.bak`. Templates fazem parte do comportamento: uma mudança de template é uma
  mudança de perfil.
- O sandbox é `allow default` + `deny network-outbound`: bloqueia egress, não acesso a arquivos.
- Porta, label do LaunchAgent e alias do modelo são todos específicos deste bundle; rodar dois perfis que
  compartilham uma porta falha rápido em vez de silenciosamente.
- A qualidade não foi medida por benchmark. Se você precisa de uma referência de qualidade, quantize
  `oQ --bits 8` a partir do BF16 oficial — e espere nenhum MTP até verificar que a cabeça sobreviveu.