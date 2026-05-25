# examples/minimal

The smallest useful cupli workspace: one container, one YAML, zero compose files.

## What it shows

* `service:` as a **dict** — inline compose-spec, no external compose file.
* `vars:` → injected as `environment` for the service.
* `ports:` → injected as `services.<name>.ports`.
* `${VAR}` interpolation in YAML, resolved from space-scope `vars`.
* Cupli's automatic wiring: `container_name: minimal-cache`,
  `networks: [default]`, env-file generation, the full `up`/`stop`/`logs`/… command set.

## Try it

```bash
cupli -f space.cupli.yaml up         # start the container
cupli -f space.cupli.yaml ps         # check it's running
cupli -f space.cupli.yaml logs cache -f
cupli -f space.cupli.yaml exec -c cache -- redis-cli ping
cupli -f space.cupli.yaml down       # stop and remove
```

## What this YAML produces

Cupli renders three generated files under `.locals/minimal/state/`:

* `docker-compose.pre.yml` — declares the `minimal` network and the default
  `container_name`.
* `docker-compose.inline.yml` — the inline compose-spec from `service:`.
* `docker-compose.post.yml` — environment injection, port mapping, network
  attachment, container name.

`docker compose` is invoked with `COMPOSE_FILE` chaining all three plus
the per-space `override.env`.
