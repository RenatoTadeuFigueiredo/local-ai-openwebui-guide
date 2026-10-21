# LocalAgent — monitoring for the local oMLX profile

Local-only Grafana stack. Nothing is exposed beyond `127.0.0.1` and nothing
starts at login.

| Piece | Where | Port |
|---|---|---|
| Exporter (reads facade, log, usage db) | host, `monitoring/exporter.py` | 8791 |
| Prometheus | container `omlx-prometheus` | 9090 |
| Grafana | container `omlx-grafana`, folder `LocalAgent` | 3300 |

```bash
./monitoring/up.sh      # after `qwen-omlx start`
./monitoring/down.sh
```

Grafana: <http://127.0.0.1:3300> — anonymous viewer, `admin` / `localagent` for
edits. The dashboard `LocalAgent — oMLX (qwen38 + sage-a15)` is provisioned from
`grafana/dashboards/localagent-omlx.json`; UI edits survive restarts because
views live in the `grafana-data` volume, but the file is the source of truth on
conflict.

## Dashboard format

The dashboard is stored in the **v2 schema** (`apiVersion:
dashboard.grafana.app/v2beta1`), because tabs only exist there: `layout` is a
`TabsLayout` with six tabs, each holding its own `GridLayout`, and panels live
in a flat `elements` map referenced by `ElementReference`.

Two details are easy to get wrong when hand-editing the file:

- the panel plugin goes in `vizConfig.group` with `kind: "VizConfig"`;
- queries are `kind: "DataQuery"` with `group: "prometheus"` and the datasource
  in `datasource: {name: "prometheus-local"}` — the string is the **datasource
  uid**;
- `annotations: []` is rejected by the CUE schema; leave the key out, while
  `links: []` is required on the dashboard *and* on every panel — a missing
  `links` makes the frontend die with `ve.links is not iterable`;
- panels carry a numeric `id`, and the `All` value of a filter variable must be
  `.*`; `$__all` leaves every `model=~"$model"` panel on "No data".

`dashboardNewLayouts` is on by default in Grafana 13, so the file renders as
tabs. The legacy `/api/dashboards/uid/...` view flattens the tabs into rows,
which is expected.

## What the exporter publishes

Request outcomes come from the facade completion lines
(`Chat completion: model=… tokens=… finish_reason=… stream_model_ttft=…`);
MTP seams come from the MTP stats lines (`accept=`, `parked for`,
`re-entry probe succeeded`); cache and error counters come from the prefix-cache
and guard lines. Cumulative tokens per model also come from `state/stats.json`,
which the server flushes periodically.

The log offset lives in `state/monitoring/exporter-offset`. A restart of the
exporter resumes where it stopped; a truncated `launcher.log` resets the
counters, because they belong to one server life.

## Panels and what "good" looks like

- **Facade / memory ceiling** — `up` and below the ceiling. A red ceiling gauge
  means the memory guard will start rejecting prefill.
- **Decode / prefill tok/s** — split per model. Sage sits around 80–115 tok/s on
  the reference M5 Max class hardware; qwen38 around 30.
- **MTP accept ratio** — 0.65–0.78 is healthy. A sustained drop below 0.55 means
  speculation is losing money and the depth controller will park.
- **Parks vs re-entries** — parks without a later success mean the standard path
  is carrying the request; a burst of them usually follows a long-context
  request on a cold cache.
- **Cache hit ratio** — high is normal for agent traffic (a big shared system
  prompt); it collapsing to zero means cache eviction or a cache-restart.
- **Errors by kind** — `handoff` must stay at zero; anything else is transient
  unless it climbs.
- **Hour buckets** — history recorded by the server before the exporter existed.
