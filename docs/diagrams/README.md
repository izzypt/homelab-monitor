# Diagrams

Everything in this folder is generated. Edit [`build.py`](build.py), never the SVG or GIF files by hand.

| Output | What it shows | Used in |
|--------|---------------|---------|
| `architecture.svg` | Every component, where it runs (internet / macOS / Colima) and who connects to whom | README §4 |
| `components/*.svg` | One card per component: where it runs, responsibilities, who it talks to | README §4 |
| `flows/*.svg` | Animated flows (SMIL) drawn on the architecture map, with a step-by-step caption | README §5 |
| `gif/*.gif` | GIF copies of the flows for slides, chats, or viewers that don't animate SVG | linked from README §5 |

The state machines, task routing and start order are Mermaid blocks written directly in the main README, so GitHub renders them as text.

## Regenerate

```bash
python3 docs/diagrams/build.py                               # SVGs (Python standard library only)
NODE_PATH=$(npm root -g) node docs/diagrams/render-gifs.mjs  # GIFs: needs playwright (Chromium) and ffmpeg
```

`render-gifs.mjs --png` writes one still per step to a temp folder instead, which is handy for checking a layout change.

## Editing

- **Facts** (responsibilities, schedules, ports, limits) live in `CARDS` and `FLOWS`. Keep them in line with `docker-compose.yml`, `backend/app` and `agent/`; when the code changes, change them here and regenerate.
- **The map** is `NODES` (centre position of each box) and `EDGES` (polyline points, label and position). Flows refer to edges by id; prefix with `-` to travel an edge backwards, and list several ids to chain them in one step.
- **A new flow** is a `Flow` with `Step`s: each step either moves a packet along edges or pulses one node (`node=`). Colours: orange request, red failure or alert path, green success or reply, blue external I/O.
- Timing is `STEP_S` per step and `MOVE_S` for the packet travel, the same for every flow.
