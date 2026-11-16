# Runpod deployment

`runpod_boot.py` runs the HAIC MCP connector on one Runpod CPU Pod. The script is the container's entire start command. It rebuilds the pinned public source on every start, then serves `https://<pod-id>-8080.proxy.runpod.net/mcp`.

This file documents the hosted endpoint in the connector README. The script is the exact bootstrap that endpoint runs (SHA-256 `4547ccbfad43987054d35f6acf2c24fcbab54ad37c4d291ab0d448cee7341e61`).

## Pinned inputs

| Input | Pin |
| --- | --- |
| Connector source | Commit `2439110ac9523cdedbc35b9b55aeeb43607468c1` of `HAIC-2026/Millrace-AI`, GitHub archive SHA-256 `d0966ffb176f5df8c5b3c83e0138cedfc89067bb32556a53f4b5258a7261dc0f` |
| Connector build | `sha256:b86b4e0a409766ab87b8f7624064ac1ad8f595135000e97674ec65501b043a9d` (engine manifest `a3a8eb8d…`) |
| Python dependencies | `haic_mcp/requirements.lock` from that commit, installed with `--require-hashes --no-deps` |
| Caddy | 2.11.9 `linux_amd64` release archive, SHA-256 `5b8cb7faf8726a2028ad96a66e54e6e81e8f361bc6175e5d22bbd997cc5177fb` |
| Container image | `python@sha256:e8c69d86735f6df3efa06b324694fe51f0422785f83a3bd463052636c2421944` (CPython 3.11.18 observed) |

The script pins the source commit, not the commit that contains this documentation. Later documentation commits do not change what a Pod runs. To deploy a newer connector, change `SOURCE_COMMIT` and `SOURCE_SHA256` together and verify the result as a new release. GitHub-generated archives are not guaranteed to stay byte-identical. If the archive hash changes, startup fails closed.

## Create a new Pod

Create a new Pod for this purpose. Do not apply this configuration to an existing Pod that runs other work. Choose your own unique Pod name.

The tested Pod used these create-Pod body fields:

| Field | Value |
| --- | --- |
| `name` | your own unique name |
| `image` | `python@sha256:e8c69d86735f6df3efa06b324694fe51f0422785f83a3bd463052636c2421944` |
| `cpu` | `{"id": "cpu3c", "vcpuCount": 2}` (2 vCPU, 4 GB RAM) |
| `cloud` | `"SECURE"` |
| `dataCenterIds` | `["US-CA-2"]` (the tested location; others are untested) |
| `disk` | `5` (GB container disk) |
| `ports` | `["8080/http"]` |
| `startSsh`, `startJupyter` | `false`, `false` |
| `entrypoint` | `["python", "-u", "-c"]` |
| `cmd` | a one-element list holding the full text of `runpod_boot.py` |

Do not add environment variables, volumes, GPU settings or other ports. The script reads only the provider-set `RUNPOD_POD_ID`.

One way to build the body file:

```sh
jq -n --rawfile boot haic_mcp/deploy/runpod_boot.py '{
  name: "your-unique-haic-mcp-name",
  image: "python@sha256:e8c69d86735f6df3efa06b324694fe51f0422785f83a3bd463052636c2421944",
  cpu: {id: "cpu3c", vcpuCount: 2}, cloud: "SECURE", dataCenterIds: ["US-CA-2"],
  disk: 5, ports: ["8080/http"], startSsh: false, startJupyter: false,
  entrypoint: ["python", "-u", "-c"], cmd: [$boot]
}' > create-pod-body.json
```

Submit the body with your own Runpod account tooling. Never put an API key in the body. Runpod assigns the Pod ID. Your endpoint is `https://<pod-id>-8080.proxy.runpod.net/mcp`.

## What the script does on each start

1. The script reads `RUNPOD_POD_ID` and derives the canonical host `<pod-id>-8080.proxy.runpod.net`.
2. The script downloads the source archive and checks its SHA-256. Absolute paths, `..`, links and other non-file members fail the start.
3. The script downloads the Caddy archive and checks its SHA-256.
4. The script creates a virtual environment and installs the hash-locked dependencies.
5. The script writes a Caddy configuration and validates it with `caddy validate`.
6. The script starts the connector on `127.0.0.1:8765`. It passes the canonical host to `--allowed-host`. It passes `https://<host>` and `https://chatgpt.com` to `--allowed-origin`.
7. The script waits up to 60 seconds for a successful MCP `initialize`. Then it starts Caddy on port 8080.
8. If the connector or Caddy exits, the script stops the other process and exits with status 1.

The state directory is `/opt/haic-state` on the container disk. In one tested stop and start, that disk was reset. The script rebuilt the service, and the URL and identity did not change. This was observed on one restart, not a documented provider guarantee. Each start depends on GitHub and PyPI serving the pinned files.

## Proxy boundary

The Runpod proxy terminates HTTPS. It forwards requests with an internal `Host` such as `100.65.20.83:60490`, and the internal port changed across restarts. The proxy sets its own `X-Forwarded-Host` header to the public host name. In tests, the proxy overwrote caller-supplied `X-Forwarded-Host` values. This is observed behavior, not a documented guarantee.

Caddy relies on that provider behavior:

- `/mcp` and `GET /healthz` match only when the provider-set `X-Forwarded-Host` equals the canonical host exactly. Every other request gets 404.
- After that match, Caddy sets the upstream `Host` to the fixed canonical host for `/mcp`. The connector's Host check then passes.
- Caddy forwards `Origin` unchanged, so the connector's Origin allowlist still applies. A hostile Origin gets 403.
- Caddy caps the request body at 131,072 bytes. Its upstream read and write timeouts are 90 seconds.
- The Caddy admin API is disabled. Caddy output is discarded, so no access log exists.

This boundary trusts the provider's header overwrite. A process inside the container could set `X-Forwarded-Host` itself. The Pod runs no other workloads.

## Known limits

- The Pod requests only `8080/http`, with `startSsh` and `startJupyter` set to false. The provider also mapped a reserved HTTP port, 19123. Its public name returned a provider 502 page, so nothing listens there. The account owner keeps authenticated provider access to the Pod.
- One Pod in one data center. There is no failover, high availability or service-level guarantee. Provider outages, account funds and provider header changes can stop the service.
- `/healthz` is a static Caddy reply. It shows that the proxy is up, not that MCP works. Check readiness with MCP `initialize` and `tools/list`.
- `GET /mcp` with `Accept: text/event-stream` opens a stream that pings keep alive. Read only the response headers.
- The provider edge rejected Python `urllib`'s default User-Agent (Cloudflare error 1010). Scripted clients need an explicit User-Agent.
- The connector stores nothing and logs only tool, status and duration. Runpod's HTTPS proxy also processes every request under Runpod's terms. The connector's no-storage statement does not cover that proxy.
- The tested shape cost $0.06 per hour of running compute and $0.50 per month for the 5 GB disk. That is about $44.30 for 730 hours of continuous running. Stopping the Pod ends compute billing. Deleting the Pod ends both charges and removes its disk.
