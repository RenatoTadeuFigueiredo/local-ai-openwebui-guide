# Client routes to a local profile

Snippets that point a coding client at the local facade on `127.0.0.1:8084`. Both clients speak
the OpenAI chat-completions API; the facade implements it, with the profile's API key as bearer.

Route the model you want; the facade serves whichever aliases the profile exposes. Nothing here
changes global defaults except where noted.

## Grok Build

Append [`grok-provider.toml`](grok-provider.toml) to `$GROK_HOME/config.toml`, replacing
`<state/api-key>` with `cat ~/models/<profile>/state/api-key`. Restart the client and pick
`local/sage-a15-omlx` or `local/qwen38-omlx` with `/model` (or set `model_provider` for the
profile).

`supports_reasoning_effort = false` on purpose: the template gates thinking with
`enable_thinking`, so `reasoning_effort` has nothing to map to and would be accepted silently.

## dsh / dsh-tui

Merge [`dsh-provider.yml`](dsh-provider.yml) into `~/.dsh/cordis.patch.yml` — the **home** layer,
which applies after every profile and therefore survives a profile patch replacing the
`llm-pi-ai` block. Then put the key in `~/.dsh/.env`:

```bash
printf 'OMLX_LOCAL_KEY=%s\n' "$(cat ~/models/<profile>/state/api-key)" >> ~/.dsh/.env
```

Verify the provider composes:

```bash
dsh --profile dsh-tui --dump-config | sed -n '/- id: llm-pi-ai/,/^- id: /p'
```

A one-shot check without touching defaults:

```bash
cat > /tmp/pick-local.yml <<'YML'
- id: agent-default-model
  config:
    provider: local-omlx
    model: sage-a15-omlx
YML
dsh --profile headless --patch /tmp/pick-local.yml "reply with exactly: ok"
```

To make a local model the default, patch `agent-default-model` and the `dsh-tui` block the same
way — and remember that a patch replaces the entry's whole config block, so replicate its other
keys.

## Operational notes

- Raise `request_timeout_secs` / `timeoutMs` before using these routes on big prompts. A cold
  prefill of an agent-sized system prompt can take a minute.
- Keep `memory_guard_tier: balanced` in the profile; `safe` rejects agent-sized prompts when two
  models are resident (see doc 08).
- One request at a time: the profile runs `max_concurrent_requests: 1`. A second client queues.
- The key is per profile. Rotating `state/api-key` breaks both routes until updated.
- Revoke by removing the provider block; nothing is installed into the clients.
