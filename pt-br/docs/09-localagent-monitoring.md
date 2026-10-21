# 9. LocalAgent — Grafana local para qualquer perfil oMLX

> **Português** · [English](../docs/09-localagent-monitoring.md)

[`examples/localagent-dashboard/`](../../examples/localagent-dashboard/) é uma stack Grafana
exclusivamente local que se acopla a **um** perfil oMLX e mostra o que aquele perfil faz de fato:
vazão de decode e prefill, tempo até o primeiro token, razão de aceitação e parks do MTP, reuso de
prefix cache, memória do engine contra o teto, erros por tipo e motivos de fim.

A stack é guiada por perfil, não por modelo. O exporter descobre quais modelos a fachada serve,
então o mesmo conjunto funciona para `qwen38-omlx`, para o alias Sage, para o perfil Ornith ou para
um perfil que você criar depois. Um perfil, uma stack, um conjunto de portas.

Tudo escuta em `127.0.0.1`. Sem túnel e sem item de login: a stack sobe quando você chama e para
quando você chama.

## 1. Requisitos

- macOS com Docker Desktop em execução.
- Um perfil no layout deste guia: `secure_server.py`, `state/api-key`, `state/launcher.log`,
  `state/usage.sqlite3` e um script de controle que carregue `PORT=<n>`.
- Três portas livres para a instância. O instalador escolhe a partir de uma base e recusa as
  ocupadas.

O Docker Desktop precisa alcançar o host; o compose já declara
`host.docker.internal:host-gateway`.

## 2. Instalação

Da raiz do repositório:

```bash
python3 examples/localagent-dashboard/install.py ~/models/<perfil> --base-port 8791
```

O instalador copia a stack para `<perfil>/monitoring/`, resolve a porta da fachada pelo próprio
script de controle do perfil, aloca `EXPORTER_PORT`, `PROM_PORT` e `GRAFANA_PORT`, escreve
`monitoring/.env` e renderiza o alvo de scrape do Prometheus. Ele recusa rodar duas vezes no mesmo
diretório.

| Instância | Base | Exporter | Prometheus | Grafana |
|---|---|---|---|---|
| primeiro perfil | 8791 | 8791 | 8891 | 8991 |
| segundo perfil | 8801 | 8801 | 8901 | 9001 |
| qualquer perfil com base explícita | `N` | `N` | `N+100` | `N+200` |

Duas instâncias nunca compartilham nome de container nem volume: o nome do projeto é a instância e
os volumes são `<instância>-{grafana,prometheus}-data`. Uma segunda instância é só outra chamada de
instalação com outra base.

## 3. Subir e parar

```bash
~/models/<perfil>/monitoring/up.sh     # depois do `start` do próprio perfil
~/models/<perfil>/monitoring/down.sh
```

O `up.sh` sobe o exporter no host com o ambiente da instância e levanta os containers. O Grafana
fica em `http://127.0.0.1:<GRAFANA_PORT>`, com a pasta `LocalAgent` e o dashboard provisionado; o
usuário admin é `admin` e a senha é `localagent`, salvo `GRAFANA_PASSWORD` no `.env`.

## 4. Verificar

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:<GRAFANA_PORT>/api/health     # 200
curl -s http://127.0.0.1:<PROM_PORT>/api/v1/targets | grep -o '"health":"[a-z]*"'        # "up"
curl -s -o /tmp/dash.png -w '%{http_code} %{size_download}\n' \
  -u admin:localagent "http://127.0.0.1:<GRAFANA_PORT>/render/d/localagent-omlx?kiosk=1&width=1400&height=900"
```

O render é a checagem real: dashboard saudável renderiza 60–90 KB com gráficos. Render de 10–15 KB
significa que o conjunto de painéis falhou, e `magick <arquivo> -format '%k\n' info:` diz se é tela
de erro plana (dezenas de cores) ou conteúdo (centenas).

## 5. Adaptar o dashboard

O dashboard fica em `grafana/dashboards/localagent-omlx.json`, no schema v2
(`dashboard.grafana.app/v2beta1`). Abas só existem ali: `layout` é um `TabsLayout`, cada aba tem um
`GridLayout` e os painéis ficam num mapa plano `elements` referenciado por `ElementReference`.

Três formas que o schema rejeita ou descarta em silêncio, todas custando uma rodada de depuração:

| Errado | Certo |
|---|---|
| `vizConfig.kind: "stat"` | `vizConfig.kind: "VizConfig"` + `group: "stat"` |
| `query.kind: "prometheus"` | `query.kind: "DataQuery"` + `group: "prometheus"`, `version: "v0"` |
| `element.kind: "ref"` | `element.kind: "ElementReference"` |

E dois padrões que quebram a página em vez de falhar na validação:

- `links: []` é obrigatório no dashboard **e** em todo painel. Sem isso o navegador mostra
  `ve.links is not iterable` e o dashboard não carrega.
- `annotations: []` é rejeitado; deixe a chave fora.
- O valor `All` de uma variável de filtro precisa ser `.*`. `$__all` deixa todo painel com
  `model=~"$model"` em "No data".

Painéis não devem fixar nome de modelo: use legenda `{{model}}` com `model=~"$model"`, para um
perfil que troca de checkpoint continuar funcionando.

## 6. Diagnóstico

| Sintoma | Causa | Correção |
|---|---|---|
| `ve.links is not iterable` | `links` ausente | `"links": []` no spec e em cada painel |
| Todo painel em "No data" | `allValue` é `$__all`, ou exporter parado | `allValue: ".*"`; confira `curl 127.0.0.1:<EXPORTER_PORT>/metrics` |
| Grafana reiniciando em loop | token do renderer padrão | defina `RENDERER_TOKEN` (o instalador faz) e mantenha igual nos dois serviços |
| `port already in use` | outra instância na mesma base | instale com outro `--base-port` |
| `omlx_healthy 0` | perfil não está rodando | suba o perfil; a stack continua raspando e preenche |
| Painéis vazios com requests acontecendo | `FACADE_URL` errada no `.env` | aponte para a porta do perfil e rode `up.sh` de novo |

## 7. Segurança

- As três portas escutam em `127.0.0.1`; nada sai da máquina.
- Acesso anônimo é **Viewer**; escrita exige a credencial admin.
- O exporter é somente leitura e não guarda segredo próprio — lê `state/api-key` no momento do
  scrape.
- O Prometheus não tem autenticação. Tudo bem em loopback, e é a peça a colocar atrás de um túnel
  primeiro se a stack sair para fora.

## 8. Remoção

```bash
~/models/<perfil>/monitoring/down.sh
cd ~/models/<perfil>/monitoring && docker compose --env-file .env down -v   # descarta o histórico
rm -rf ~/models/<perfil>/monitoring
```

O `down.sh` preserva os volumes; `down -v` os apaga.
