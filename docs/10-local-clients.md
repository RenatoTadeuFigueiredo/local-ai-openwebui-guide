# 10. Routing local clients (Grok Build, dsh)

> **English** · [Português](../../pt-br/docs/10-local-clients.md)

Two clients on this machine can talk to the local profile instead of a cloud provider: Grok Build
and `dsh` / `dsh-tui`. Both use the OpenAI chat-completions API, which the facade already
implements behind the profile's bearer key.

Snippets live in [`examples/local-client-routes/`](../../examples/local-client-routes/); this page
covers the moving parts and the failure modes.

## Grok Build

Append the provider block from
[`grok-provider.toml`](../../examples/local-client-routes/grok-provider.toml) to the active
`$GROK_HOME/config.toml`, substitute the key, restart, then `/model` to `local/sage-a15-omlx` or
`local/qwen38-omlx`.

Capabilities matter here. The profile template gates reasoning with `enable_thinking`, not with
`reasoning_effort`, so the route declares `supports_reasoning_effort = false`; leaving it on makes
the client send a knob the template ignores. `supports_image_input` is only true for the Sage
alias, which ships a vision tower.

## dsh / dsh-tui

`dsh` composes profile layers in order: shipped bundles, your profile patch, then the home layer at
`~/.dsh/cordis.patch.yml`. Both the shipped profile and the home layer patch `llm-pi-ai`, and a
patch replaces the entry's whole config block — so the provider belongs in the **home** layer.
Putting it in the profile patch works until the next shipped-bundle update composes over it.

```bash
# 1. merge examples/local-client-routes/dsh-provider.yml into ~/.dsh/cordis.patch.yml
# 2. key, outside the YAML
printf 'OMLX_LOCAL_KEY=%s\n' "$(cat ~/models/<profile>/state/api-key)" >> ~/.dsh/.env
# 3. prove it composes
dsh --profile dsh-tui --dump-config | sed -n '/- id: llm-pi-ai/,/^- id: /p'
# 4. one-shot answer against the local model, defaults untouched
dsh --profile headless --patch /tmp/pick-local.yml "reply with exactly: ok"
```

`apiKeyEnv` resolves through the credential store, the launch environment and finally
`~/.dsh/.env` — the key never enters a tracked file.

## Why the manifests carry timeouts and context

- `request_timeout_secs = 600` / `timeoutMs = 900000`: a cold prefill of an agent-sized system
  prompt is minutes, not seconds. A client that gives up at 60 s reports a healthy server as
  broken.
- `context_window = 262144`: native for both checkpoints here. Declaring less truncates silently;
  declaring more makes the server reject the tail.
- `max_completion_tokens = 8192`: matches the profile's output cap. Higher values do not extend
  the answer, the server clips at its own ceiling.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Model missing from the picker | provider block in the wrong layer, or `enabled = false` | home layer, `enabled = true`, restart the client |
| 401 on every request | key rotated | re-read `state/api-key` into the config |
| 400 with a memory-guard message | two models resident and tier `safe` | set `memory_guard_tier: balanced` |
| Requests hang then fail | client timeout below the prefill | raise the timeout in the provider block |
| Second client stalls | `max_concurrent_requests: 1` | expected; it queues |

## Coexistence notes

Both clients share one facade and one key. The profile's `idle_timeout_seconds: 600` unloads the
model after ten idle minutes, costing a reload on the next call; the first request after that is
slow by design rather than by fault.
