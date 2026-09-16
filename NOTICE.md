# NOTICE

> **English** · [Português](pt-br/NOTICE.md)

## What this repository is

A documented **personal deployment** of local AI on a Mac. Not an official publication of any
vendor, and not a replacement for any vendor's documentation.

## Licenses

| Scope | License |
|---|---|
| `docs/`, `pt-br/`, root `README.md` | [CC BY 4.0](LICENSE) |
| `examples/` (code) | [MIT](LICENSE-CODE) |

The split is deliberate: documentation is prose and the CC license is made for text; code is
software and MIT is made for code.

## Authorship

Written and executed by Renato Tadeu Figueiredo. The numbers, measurements and states reported come
from the author's machine, between August and September 2026.

## Third-party components

No third-party code is vendored here, but the documents describe and configure:

| Component | Origin |
|---|---|
| Open WebUI | <https://github.com/open-webui/open-webui> |
| oMLX | <https://github.com/jundot/omlx> |
| MLX / mlx-lm / mlx-vlm | Apple |
| cloudflared | Cloudflare |
| Qwen3.8-27B and the derived checkpoint | Alibaba Qwen / `fcmeyer` |
| Chromium, Playwright, FastAPI, uvicorn, PyJWT | respective maintainers |
| `@piotr-agier/google-drive-mcp` | Piotr Agier |
| Container and seccomp profiles | Docker / Moby project |

Specific versions are pinned in the documents and in the `pyproject.toml` / `requirements-*.txt`
files.

## Trademarks

Product names mentioned — **macOS**, **Apple Silicon**, **Cloudflare**, **Docker**, **Chromium**,
**Qwen** — belong to their respective owners. Their use here is descriptive.

## Measurements and projections

The documents distinguish, where relevant, what was **measured** from what was **estimated** or
**extrapolated**. A number measured on one machine is not a performance promise for another:
temperature, machine state, runtime version and concurrent load all change the result.

## No warranty

Provided as-is. The documents describe commands that change system configuration, install services
and publish hostnames — running them is the responsibility of whoever runs them.

## Corrections

If a command no longer works, or a vendor changed something, open an issue with:

- the document and the exact passage
- the version of the component involved
- what happened instead of what was expected

Corrections are welcome. This repository's value depends on it staying true. See
[`CONTRIBUTING.md`](CONTRIBUTING.md).