# 9. LocalAgent — local Grafana for any oMLX profile

> **English** · [Português](../../pt-br/docs/09-localagent-monitoring.md)

[`examples/localagent-dashboard/`](../../examples/localagent-dashboard/) is a local-only
Grafana stack that attaches to one oMLX profile and charts what that profile actually does:
decode and prefill throughput, time to first token, MTP accept ratio and parks, prefix-cache
reuse, engine memory against the ceiling, errors by kind and finish reasons.

It is profile-driven, not model-driven. The exporter discovers whatever models the facade
serves, so the same stack works for `qwen38-omlx`, for the Sage alias, for the Ornith profile, or
for a profile you create later. One profile, one stack, one set of ports.

Everything binds `127.0.0.1`. There is no tunnel and no login item: the stack starts when you
call it and stops when you call it.

## 1. Requirements

- macOS with Docker Desktop running.
- A profile laid out like this guide's: `secure_server.py`, `state/api-key`, `state/launcher.log`,
  `state/usage.sqlite3`, and a control script that carries `PORT=<n>`.
- Three free ports for this instance. The installer picks them from a base and refuses to reuse
  busy ones.

Docker Desktop must reach the host; the compose file already declares
`host.docker.internal:host-gateway`.

## 2. Install

From the repository root:

```bash
python3 examples/localagent-dashboard/install.py ~/models/<profile> --base-port 8791
```

The installer copies the stack to `<profile>/monitoring/`, resolves the facade port from the
profile's own control script, allocates `EXPORTER_PORT`, `PROM_PORT` and `GRAFANA_PORT`, writes
`monitoring/.env` and renders the Prometheus scrape target. It refuses to run twice over the same
directory.

| Instance | Base | Exporter | Prometheus | Grafana |
|---|---|---|---|---|
| first profile | 8791 | 8791 | 8891 | 8991 |
| second profile | 8801 | 8801 | 8901 | 9001 |
| any profile with an explicit base | `N` | `N` | `N+100` | `N+200` |

Two instances never share a container name or a volume: the project name is the instance, and the
volumes are `<instance>-{grafana,prometheus}-data`. A second instance is just another install call
with another base.

## 3. Start and stop

```bash
~/models/<profile>/monitoring/up.sh     # after the profile's own `start`
~/models/<profile>/monitoring/down.sh
```

`up.sh` starts the host exporter with the instance's environment and brings the containers up.
Grafana lands on `http://127.0.0.1:<GRAFANA_PORT>` with folder `LocalAgent` and the dashboard
provisioned; the admin user is `admin` and the password is `localagent` unless
`GRAFANA_PASSWORD` is set in `.env`.

## 4. Verify

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:<GRAFANA_PORT>/api/health     # 200
curl -s http://127.0.0.1:<PROM_PORT>/api/v1/targets | grep -o '"health":"[a-z]*"'        # "up"
curl -s -o /tmp/dash.png -w '%{http_code} %{size_download}\n' \
  -u admin:localagent "http://127.0.0.1:<GRAFANA_PORT>/render/d/localagent-omlx?kiosk=1&width=1400&height=900"
```

The render is the real check: a healthy dashboard renders 60–90 KB with charts. A 10–15 KB render
means the panel set failed, and `magick <file> -format '%k\n' info:` tells you whether it is a
flat error screen (tens of colours) or content (hundreds).

## 5. Adapting the dashboard

The dashboard lives in `grafana/dashboards/localagent-omlx.json`, in the v2 schema
(`dashboard.grafana.app/v2beta1`). Tabs exist only there: `layout` is a `TabsLayout`, each tab
holds a `GridLayout`, and panels sit in a flat `elements` map referenced by `ElementReference`.

Three shapes the schema rejects or silently drops, all of which cost a debugging round:

| Wrong | Right |
|---|---|
| `vizConfig.kind: "stat"` | `vizConfig.kind: "VizConfig"` + `group: "stat"` |
| `query.kind: "prometheus"` | `query.kind: "DataQuery"` + `group: "prometheus"`, `version: "v0"` |
| `element.kind: "ref"` | `element.kind: "ElementReference"` |

And two defaults that break the page instead of failing validation:

- `links: []` is required on the dashboard **and** on every panel. Missing it gives
  `ve.links is not iterable` in the browser and the dashboard never loads.
- `annotations: []` is rejected; leave the key out.
- A filter variable's `All` value must be `.*`. `$__all` leaves every `model=~"$model"` panel on
  "No data".

Panels should never hardcode a model name: use `{{model}}` legends with `model=~"$model"` so a
profile that swaps checkpoints keeps working.

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ve.links is not iterable` | `links` missing | add `"links": []` to the dashboard spec and every panel |
| Every panel "No data" | `allValue` is `$__all`, or the exporter is down | set `allValue: ".*"`; check `curl 127.0.0.1:<EXPORTER_PORT>/metrics` |
| Grafana restarts in a loop | default renderer token | set `RENDERER_TOKEN` (the installer does) and keep it identical in both services |
| `port already in use` | another instance on the same base | install with a different `--base-port` |
| `omlx_healthy 0` | profile not running | start the profile; the stack keeps scraping and fills in |
| Panels empty while requests happen | wrong `FACADE_URL` in `.env` | point it at the profile's port and `up.sh` again |

## 7. Security

- All three ports bind `127.0.0.1`; nothing leaves the machine.
- Anonymous access is **Viewer**; writes need the admin credential.
- The exporter is read-only and holds no secret of its own — it reads `state/api-key` at scrape
  time.
- Prometheus has no auth. That is fine on loopback, and it is the piece to put behind a tunnel
  first if the stack ever goes remote.

## 8. Teardown

```bash
~/models/<profile>/monitoring/down.sh
cd ~/models/<profile>/monitoring && docker compose --env-file .env down -v   # drops the history
rm -rf ~/models/<profile>/monitoring
```

`down.sh` keeps the volumes; `down -v` deletes them.
