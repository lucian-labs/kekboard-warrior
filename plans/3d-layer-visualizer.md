# 3D Layer Visualizer

Alternate view for kekboard-warrior that renders all layers as floating planes in 3D space with connections drawn between them to visualize workflows.

## The Space

- Each layer is a translucent plane floating vertically stacked with gaps
- Layer 0 at the bottom, higher layers above
- Each plane has the 23-key Corne layout rendered as interactive 3D blocks
- Active layer plane is brighter and slightly larger
- Camera smoothly elevates when holding MO() keys on the physical Corne

## Keys

- 3D rounded rectangles (`RoundedBoxGeometry`) on each plane
- Mapped keys glow with their layer color
- Unmapped keys are dim/wireframe
- Press a key on the physical Corne → corresponding 3D key animates (press down, glow)
- Click a key in 3D → opens the mapping editor (same data, same API)

## Lines / Connections

| Type | Visual | Meaning |
|------|--------|---------|
| `MO()` | Vertical beam of light between layers | Elevator shaft — pulses when held |
| `TG()` sequences | Curved arcs between source and destination planes | Portal — color-coded, arrow heads show direction |
| `KC_TRNS` | Faint dotted line dropping down | Fallthrough chain to the layer where the key is defined |
| Chord sequences | Ribbon connecting chord keys, then arc to destination | Multi-key portal activation |

## Interaction

- Orbit / zoom with mouse (OrbitControls)
- Physical Corne input highlights keys in real-time via Gamepad API
- Click keys in 3D to edit mappings
- Layer planes can be dragged vertically to reorder
- Toggle labels: matrix positions, action names, or keycodes
- Dim/hide layers to focus

## Tech

- Three.js + OrbitControls
- `PlaneGeometry` with custom shader for translucent layer planes
- `RoundedBoxGeometry` for keys
- `TubeGeometry` for arcs between layers
- `Line2` for vertical beams
- `CSS2DRenderer` overlay for crisp text labels
- Same Gamepad API polling as the 2D view

## Data Flow

- Same server API, same preset JSON — 3D is just an alternate renderer
- URL param: `&view=3d` or separate `view3d.html`
- 2D flat view stays as the primary editing mode
- 3D is for visualization, presentation, and understanding escape paths

## Implementation

1. `view3d.html` — standalone page, loads Three.js from CDN
2. Fetches device + preset from server API
3. Builds the scene from keymap data
4. Gamepad API polling loop same as 2D view
5. Shared utility functions extracted if needed

## Priority

Nice-to-have after core firmware generation is working. Good for demos, onboarding, and debugging complex layer stacks.
