# browser-hitl-poc — implementação de referência

Broker multiusuário de navegador com perfis Chromium persistentes, isolamento por usuário e
**takeover humano fenced**: o agente e a pessoa compartilham a mesma sessão/aba, e o broker impede
controle ou observação concorrente durante o login humano.

Este diretório é a **implementação de referência** do que o documento
[`../../docs/04-browser-hitl-multiusuario-poc.md`](../../docs/04-browser-hitl-multiusuario-poc.md)
descreve. Leia o documento primeiro; o código aqui existe para quem quer ver como o
comportamento foi construído.

> **Não é um projeto para clonar e sair rodando.** Ele reflete uma implantação concreta. Para
> reproduzir, gere os seus próprios segredos, escolha o seu domínio e ajuste a configuração.

---

## O que tem aqui

| Arquivo | Papel |
|---|---|
| `browser_hitl/runtime.py` | Ciclo de vida do Chromium, perfis persistentes, flags e política |
| `browser_hitl/api.py` | Endpoints HTTP, handshake de takeover, lock server-side |
| `browser_hitl/security.py` | Validação de identidade Cloudflare Access, TTL e epoch |
| `browser_hitl/store.py` | Estado, ownership por UUID e auditoria |
| `browser_hitl/egress_proxy.py` | Proxy de saída com allowlist |
| `browser_hitl/settings.py` | Configuração por variáveis de ambiente |
| `openwebui/browser_hitl_tool.py` | Tool nativa do Open WebUI |
| `tests/` | 8 arquivos, 789 linhas, cobrindo lock, isolamento, hardening e takeover |
| `chromium-seccomp.json` | Perfil seccomp (`defaultAction: SCMP_ACT_ERRNO`) |
| `chromium-policy.json` | Política de navegador |
| `compose.yaml` | Execução em container, com `cap_drop: ALL` e `no-new-privileges` |

## Rodar

```bash
cd examples/browser-hitl-poc

# 1. configuração — os modelos estão versionados, os reais não
cp .env.example .env
for k in tool-api-key admin-api-key portal-signing-key; do
  cp "secrets/$k.example" "secrets/$k"
  python3 -c "import secrets;print(secrets.token_urlsafe(48),end='')" > "secrets/$k"
  chmod 600 "secrets/$k"
done

# 2. testes
python3 -m venv .test-venv
. .test-venv/bin/activate
pip install -e '.[test]'
pytest -q

# 3. subir (Docker)
docker compose up --build
```

O serviço escuta em `127.0.0.1:3210`. O container roda como usuário não-root `cptr`, com
`HOME=/home/cptr` — é o usuário *dentro do container*, não o seu.

## Configuração

Todas as chaves vêm de variáveis de ambiente, com prefixo `BROWSER_HITL_`. As que importam:

| Variável | Para que serve |
|---|---|
| `BROWSER_HITL_PUBLIC_BASE_URL` | URL pública do portal |
| `BROWSER_HITL_ACCESS_REQUIRED` | Exige identidade Cloudflare Access |
| `BROWSER_HITL_ACCESS_TEAM_DOMAIN` | Domínio da equipe Access (`https://<time>.cloudflareaccess.com`) |
| `BROWSER_HITL_ACCESS_AUDIENCE` | AUD da aplicação Access — **troque pelo seu** |
| `BROWSER_HITL_HUMAN_CONTROL_TTL_SECONDS` | Prazo absoluto do takeover humano |
| `BROWSER_HITL_*_SECRET_FILE` | Caminho dos três segredos montados em `/run/secrets/` |

## Segurança

O desenho assume que o portal fica **publicado** e trata a identidade como não confiável:

- segredos em arquivos `0600`, montados `read_only`, nunca em variável de ambiente do host
- `cap_drop: ALL`, `no-new-privileges`, seccomp com negação por padrão
- lock server-side (`423`) entre agente e humano, com epoch para retomada
- validação do JWT do Access antes de qualquer operação privilegiada

Os segredos versionados aqui são os **reais da implantação** — publicá-los é intencional, e o
Access ainda exige One-Time PIN. Se você rodar o seu, gere os seus.

---

Documento que descreve este POC: [`../../docs/04-browser-hitl-multiusuario-poc.md`](../../docs/04-browser-hitl-multiusuario-poc.md)