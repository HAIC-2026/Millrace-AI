# Reopen a historical R2 case

The `r2` input profile replays historical cases with complete, unchanged retained inputs. It uses the original full-archive verifier. It does not make missing archive bytes pass verification. The public factual projection cannot substitute for those inputs.

The required identities are:

| Identity | SHA-256 |
| --- | --- |
| Historical source release manifest | `686b23b6b7623d77f084ed4518e6d5adec620fbe713e17ee220caa63bce2e46d` |
| Historical data snapshot | `22642501f4c8829262c5724d3a09ce1f60ed0a0c06792f4e6c0c9b829c8f3a15` |
| Historical metadata snapshot | `aa099d72a405511339867b1ab3987686bd5a07319406516a1a4500e2ae913679` |
| Historical combined evidence snapshot | `143fb7cbdf10a8a3b05a30228e44c347a2cd21d93819a3a3e79094dc847887d3` |

[R2-INPUTS.json](R2-INPUTS.json) lists all 93 required files and their exact sizes and hashes. These are the 85 runtime data files, two packet manifests, five metadata payloads, and one metadata manifest. Their hashes identify bytes and do not grant redistribution rights. Keep the retained directory private. It contains captured source materials omitted from the public projection.

1. Locate your complete retained R2 release or input directory.
2. Install only the required inputs into a new private directory:

```sh
.venv/bin/python tools/retain_r2_inputs.py --from-dir /absolute/retained-r2 --output "$HOME/.local/share/millrace-r2-inputs"
.venv/bin/python tools/retain_r2_inputs.py --check "$HOME/.local/share/millrace-r2-inputs"
```

The installer verifies every inventory hash before copying. It refuses an existing destination. It verifies the copied archive again and performs no network requests. Missing or changed historical bytes cause failure. Use the matching live R2 app if you lack the archive. The current source tools cannot reconstruct omitted historical pages or exact old captures.

3. Start this source build with the verified historical inputs:

```sh
HAIC_INPUT_PROFILE=r2 HAIC_R2_INPUT_DIR="$HOME/.local/share/millrace-r2-inputs" HAIC_STATE_DIR="$HOME/.local/state/millrace-r2" HAIC_LOCAL_HTTP=1 PORT=8081 .venv/bin/gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8081 wsgi:application
```

Open [the local R2 profile](http://127.0.0.1:8081), select a saved case, and review its preview. Accept staff work only when intended. The importer regenerates facts from the matching evidence snapshot. It preserves the historical branch release ID, branch ID and exact canonical selections. Imported staff notes, checklist progress and tracking require review before a brief.

The bootstrap `release_id` describes this current source build. A saved branch's `release_id` remains historical provenance. Replay requires matching evidence, operation and recipe versions plus canonical claim and action identities. It does not accept arbitrary data archives based on a saved release label. Unknown snapshots remain unavailable.
