# NOTICE

> [English](../NOTICE.md) · **Português**

## O que é este repositório

Registro documentado de uma **implantação pessoal** de IA local em um Mac. Não é publicação
oficial de nenhum fornecedor, e não substitui a documentação de nenhum deles.

## Licenças

| Escopo | Licença |
|---|---|
| `docs/` e este README | [CC BY 4.0](../LICENSE) |
| `examples/` (código) | [MIT](../LICENSE-CODE) |

A separação é intencional: a documentação é prosa e a licença CC é feita para texto; o código é
software e a MIT é feita para código.

## Autoria

Escrito e executado por Renato Tadeu Figueiredo. Os números, medições e estados relatados vêm da
máquina do autor, em agosto e setembro de 2026.

## Componentes de terceiros

Nenhum código de terceiros está vendorizado aqui, mas os documentos descrevem e configuram:

| Componente | Origem |
|---|---|
| Open WebUI | <https://github.com/open-webui/open-webui> |
| oMLX | <https://github.com/jundot/omlx> |
| MLX / mlx-lm / mlx-vlm | Apple |
| cloudflared | Cloudflare |
| Qwen3.8-27B e checkpoint derivado | Alibaba Qwen / `fcmeyer` |
| Chromium, Playwright, FastAPI, uvicorn, PyJWT | respectivos mantenedores |
| `@piotr-agier/google-drive-mcp` | Piotr Agier |
| Contêineres e perfis seccomp | projeto Docker / Moby |

Versões específicas estão fixadas nos documentos e nos `pyproject.toml` / `requirements-*.txt`.

## Marcas

Nomes de produtos citados — **macOS**, **Apple Silicon**, **Cloudflare**, **Docker**,
**Chromium**, **Qwen** — pertencem aos seus respectivos donos. O uso aqui é descritivo.

## Medições e projeções

Os documentos distinguem, quando relevante, o que foi **medido** do que foi **estimado** ou
**extrapolado**. Um número medido numa máquina não é promessa de desempenho em outra: temperatura,
estado da máquina, versão de runtime e carga concorrente mudam o resultado.

## Sem garantia

Fornecido como está. Os documentos descrevem comandos que alteram configuração de sistema, instalam
serviços e publicam hostnames — executá-los é responsabilidade de quem executa.

## Correções

Se um comando não funciona mais, ou um fornecedor mudou algo, abra uma issue com:

- o documento e o trecho exato
- a versão do componente envolvido
- o que aconteceu em vez do esperado

Correções são bem-vindas. O valor deste repositório depende de ele permanecer verdadeiro.