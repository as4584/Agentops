# OpenScreen Demo Creator

> Capture and export polished demos of Agentop's control center UI.

## Purpose
Create professional screen recordings and GIF demos of the Agentop dashboard, agent floor, and pipeline visualizations for:
- Career fair presentations
- Portfolio showcase
- README documentation
- Social media clips

## Workflow

### Phase 1: Setup Recording Environment
1. Ensure frontend is running on `localhost:3007`
2. Ensure backend is healthy: `curl localhost:8000/health`
3. Set viewport size: 1920x1080 (full) or 800x600 (GIF)

### Phase 2: Capture via Browser Automation
Use `browser_control` to navigate and interact:
```
browser_control("navigate", agent_id, url="http://localhost:3007")
browser_control("screenshot", agent_id)  # capture frame
```

For video: use `safe_shell` with ffmpeg:
```bash
# Record X11 display (or Xvfb for headless)
ffmpeg -f x11grab -video_size 1920x1080 -i :0 -t 30 -c:v libx264 -preset fast output/demo.mp4
```

### Phase 3: Create GIF
```bash
# Convert MP4 to GIF with palette optimization
ffmpeg -i output/demo.mp4 -vf "fps=10,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" output/demo.gif
```

### Phase 4: Annotate
Use ffmpeg drawtext filter for annotations:
```bash
ffmpeg -i output/demo.mp4 -vf "drawtext=text='Agentop Control Center':x=20:y=20:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.6" output/demo_annotated.mp4
```

## Demo Scenarios
1. **Agent Floor** — Navigate to dashboard, show all agents in visual states
2. **Chat Interaction** — Send a message, watch routing + agent response
3. **Pipeline Run** — Trigger content or webgen pipeline, show progress
4. **Health Dashboard** — Show system health, drift status, tool logs
5. **Customer Management** — CRUD operations in customer panel

## Output
- `output/demos/` — MP4 and GIF files
- `output/demos/thumbnails/` — First-frame PNGs for README embedding

## Requirements
- `ffmpeg` installed (check: `which ffmpeg`)
- Frontend running on port 3007
- Backend healthy on port 8000
- For headless: `Xvfb` for virtual display
