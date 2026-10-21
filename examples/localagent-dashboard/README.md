# LocalAgent — local monitoring for an oMLX profile

Local-only Grafana stack: a host exporter reads one profile's facade, completion log and usage
database, Prometheus keeps 30 days, and Grafana provisions the folder `LocalAgent` with a tabbed
dashboard (overview, MTP, cache, traffic, errors, history).

It is per **profile**, not per model: the exporter discovers whatever models the facade serves, so
a profile that swaps checkpoints keeps working without edits.

Full procedure — install, multi-instance ports, verification, schema traps, teardown:
[`docs/09-localagent-monitoring.md`](../../docs/09-localagent-monitoring.md).

## Install into a profile

```bash
python3 examples/localagent-dashboard/install.py ~/models/<profile> --base-port 8791
```

The installer copies this stack to `<profile>/monitoring/`, reads the facade port from the
profile's own control script, and writes `.env` with three free ports. It refuses to overwrite an
existing installation.

## Operate

```bash
~/models/<profile>/monitoring/up.sh      # after the profile's own start
~/models/<profile>/monitoring/down.sh
```

Grafana lands on `http://127.0.0.1:<GRAFANA_PORT>`; anonymous access is Viewer, `admin` /
`localagent` for edits. Nothing starts at login and every port binds `127.0.0.1`.

## Layout

| Path | Role |
|---|---|
| `exporter.py` | Host exporter, configured by `PROFILE_ROOT` / `FACADE_URL` / `API_KEY_FILE` / `LOG_FILE` / `EXPORTER_PORT` |
| `docker-compose.yml` | Prometheus, Grafana and the image renderer, named and ported per `${INSTANCE}` |
| `prometheus/prometheus.yml` | Scrape target rendered by the installer |
| `grafana/dashboards/localagent-omlx.json` | The dashboard, v2 schema with a `TabsLayout` |
| `grafana/provisioning/` | Datasource and dashboard provider |

## What the exporter publishes

Request outcomes come from the facade completion lines
(`Chat completion: model=… tokens=… finish_reason=… stream_model_ttft=…`); MTP seams come from the
MTP stats lines (`accept=`, `parked for`, `re-entry probe succeeded`); cache and error counters come
from the prefix-cache and guard lines. Cumulative tokens per model also come from
`state/stats.json`, which the server flushes periodically.

The log offset lives in `state/monitoring/exporter-offset`. A restart of the exporter resumes where
it stopped; a truncated `launcher.log` resets the counters, because they belong to one server life.

## What "good" looks like

- **Facade / memory ceiling** — `up` and below the ceiling. A red ceiling gauge means the memory
  guard will start rejecting prefill.
- **Decode / prefill tok/s** — split per model. Sage sits around 80–115 tok/s on M5 Max class
  hardware; qwen38 around 30.
- **MTP accept ratio** — 0.65–0.78 is healthy. A sustained drop below 0.55 means speculation is
  losing money and the depth controller will park.
- **Parks vs re-entries** — parks without a later success mean the standard path is carrying the
  request; a burst usually follows a long-context request on a cold cache.
- **Cache hit ratio** — high is normal for agent traffic (a big shared system prompt); collapsing to
  zero means eviction or a restart.
- **Errors by kind** — `handoff` must stay at zero; anything else is transient unless it climbs.
