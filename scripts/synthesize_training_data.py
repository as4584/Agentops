#!/usr/bin/env python3
"""
scripts/synthesize_training_data.py
────────────────────────────────────
Generate ShareGPT fine-tuning pairs from local source files + curated 3D web seeds.
Feeds Claude (Sonnet/Opus) raw content and asks it to produce high-quality Q&A pairs
in the user's voice—ready for Unsloth QLoRA fine-tuning.

Quick start:
  export ANTHROPIC_API_KEY=sk-ant-...
  python scripts/synthesize_training_data.py --domain agentop
  python scripts/synthesize_training_data.py --sources /mnt/c/Users/Lex/NJIT --domain njit
  python scripts/synthesize_training_data.py --domain 3d-web
  python scripts/synthesize_training_data.py --sources . /mnt/c/Users/Lex/NJIT --domain all

Output:  data/training/<domain>_<timestamp>.jsonl   (ShareGPT format)

ShareGPT format per line:
  {"conversations": [{"from": "human", "value": "..."}, {"from": "gpt", "value": "..."}]}

GPU note (RTX 4070 / 12GB VRAM):
  Target model for fine-tuning: Qwen2.5-7B-Instruct (4-bit QLoRA = ~5GB VRAM)
  Fine-tuning command (after data is collected):
    unsloth_zoo finetune --model Qwen/Qwen2.5-7B-Instruct --data data/training/ \\
      --output models/lex_7b_finetune --epochs 3 --lora-r 16
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterator

# ── optional PDF support ─────────────────────────────────────────────────────
try:
    from pypdf import PdfReader as _PdfReader  # type: ignore

    PDF_AVAILABLE = True
except ImportError:
    _PdfReader = None  # type: ignore[assignment,misc]
    PDF_AVAILABLE = False

from typing import Any

try:
    import anthropic as _anthropic  # type: ignore
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    _anthropic = None  # type: ignore[assignment]

# ── repo paths ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "training"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Ollama (local, no API key needed) ─────────────────────────────────────────
OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# ── directories to skip when scanning ────────────────────────────────────────
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".next", "dist", "build", "output", ".mypy_cache",
    "animation_salvage_lab", "pixel-agents", "SigmaSimulator",
    ".ruff_cache", "logs", "reports",
}

# ── file extensions to include ────────────────────────────────────────────────
TEXT_EXTS = {".md", ".txt", ".py", ".ts", ".tsx", ".js", ".jsx",
             ".html", ".css", ".json", ".toml", ".yaml", ".yml", ".sh"}

CHUNK_SIZE = 2_800   # ~700 tokens — sweet spot for instruction extraction
CHUNK_OVERLAP = 200  # chars of overlap between chunks

# ── domain-specific source subdirs inside ROOT ─────────────────────────────────
DOMAIN_DIRS: dict[str, list[str]] = {
    "agentop": [
        "backend", "docs", "frontend/src", ".github/prompts",
        "backend/skills/data",
    ],
    "ibds": ["clients/ibds"],
    "webgen": ["seagullmedterwebsite", "backend/webgen"],
    "njit": [],   # user provides --sources path
    "3d-web": [], # seeds only — no local scan needed
    "all": [      # everything except NJIT (user must add --sources)
        "backend", "docs", "clients", "seagullmedterwebsite",
        "backend/webgen", ".github/prompts",
    ],
}

# ── model aliases ─────────────────────────────────────────────────────────────
MODELS = {
    "haiku":  "claude-haiku-4-5",    # fastest / cheapest — bulk low-value chunks
    "sonnet": "claude-sonnet-4-5",   # balanced — good default
    "opus":   "claude-opus-4-5",     # highest quality — 3d-web / critical domains
}

# ── system prompts per domain ──────────────────────────────────────────────────
SYSTEM_PROMPTS: dict[str, str] = {
    "agentop": """You are a NJIT CS student named Lex who built Agentop — a production-grade \
multi-agent system with FastAPI, LangGraph, Ollama, and a Next.js dashboard. \
You understand agent orchestration, drift governance, tool call security, and \
local LLM deployment deeply. Turn the provided source material into 5–8 \
HIGH-QUALITY conversational Q&A pairs that reflect how Lex would explain this \
code/architecture to a fellow engineer. Each answer should be detailed, \
opinionated, and reference specifics from the material. \
Reply with ONLY a JSON array of {"q": "...", "a": "..."} objects. No markdown wrappers.""",

    "ibds": """You are Lex, a software engineer and AI consultant who built the IBDS \
(Innovation Development Solutions) platform — a Next.js + Mantine enterprise AI dashboard \
with agent orchestration, a GSD task system, and multi-tenant capabilities. \
Turn the provided spec/code into 5–8 Q&A training pairs showing deep understanding \
of the architecture, component decisions, and business rationale. \
Reply ONLY with a JSON array of {"q": "...", "a": "..."} objects.""",

    "webgen": """You are Lex, a web developer who builds high-conversion, beautifully designed \
restaurant and business websites using HTML, CSS, and vanilla JS. You understand \
SEO, AEO (Answer Engine Optimization), performance budgets, and brand identity. \
Turn the provided HTML/CSS/JS source into 5–8 Q&A pairs that teach how to build \
sites like this — covering layout patterns, animation techniques, color systems, \
and conversion optimization. Reply ONLY with a JSON array of {"q": "...", "a": "..."} objects.""",

    "njit": """You are Lex, a NJIT Computer Science student. Turn the provided coursework \
material (notes, assignments, code) into 5–8 Q&A pairs that would help a CS student \
master this material. Make answers clear, accurate, and show real understanding — \
not just surface definitions. Prefer examples. \
Reply ONLY with a JSON array of {"q": "...", "a": "..."} objects.""",

    "3d-web": """You are Lex, a front-end engineer who specializes in building visually \
stunning 3D and animated web experiences using Three.js, GSAP ScrollTrigger, \
CSS 3D transforms, WebGL shaders, and Canvas APIs. You produce self-contained \
HTML/JS files that work without a build step. Your code is clean, commented, \
and demonstrates mastery of web animation and 3D rendering. \
Turn the provided reference material into 5–8 Q&A pairs where the answer \
includes complete, working code examples. \
Reply ONLY with a JSON array of {"q": "...", "a": "..."} objects.""",

    "all": """You are Lex Santiago — NJIT CS student, AI agency founder, and full-stack \
engineer who built Agentop and production client websites. Turn the provided \
source material into 5–8 Q&A training pairs in Lex's voice: practical, direct, \
opinionated, and technically precise. Include code examples where relevant. \
Reply ONLY with a JSON array of {"q": "...", "a": "..."} objects.""",
}

# ── curated 3D web seed Q&A pairs ─────────────────────────────────────────────
# These are injected directly (no API call needed) — golden training examples
# that teach Three.js, GSAP, WebGL, and CSS 3D patterns.
THREE_D_WEB_SEEDS: list[dict] = [
    {
        "q": "How do I build a Three.js particle hero background that feels premium and works on mobile?",
        "a": """Here's a self-contained Three.js particle hero that uses BufferGeometry for performance
and fades particles based on distance — so mobile gets fewer particles automatically:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #060612; overflow: hidden; }
  canvas { position: fixed; inset: 0; }
  .hero-text {
    position: fixed; inset: 0;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    color: #fff; font-family: 'Inter', sans-serif;
    pointer-events: none; z-index: 10;
  }
  h1 { font-size: clamp(2.5rem, 7vw, 5rem); font-weight: 700;
       background: linear-gradient(135deg, #fff 0%, #a78bfa 100%);
       -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
</style>
</head>
<body>
<canvas id="c"></canvas>
<div class="hero-text"><h1>Your Brand Name</h1></div>
<script src="https://cdn.jsdelivr.net/npm/three@0.165.0/build/three.min.js"></script>
<script>
const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById('c'), antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(60, innerWidth / innerHeight, 0.1, 1000);
camera.position.z = 80;

// Particle count scales with viewport for mobile perf
const COUNT = Math.min(3000, Math.floor(innerWidth * innerHeight / 400));
const geo = new THREE.BufferGeometry();
const positions = new Float32Array(COUNT * 3);
const sizes = new Float32Array(COUNT);
for (let i = 0; i < COUNT; i++) {
  positions[i * 3]     = (Math.random() - 0.5) * 200;
  positions[i * 3 + 1] = (Math.random() - 0.5) * 200;
  positions[i * 3 + 2] = (Math.random() - 0.5) * 200;
  sizes[i] = Math.random() * 2 + 0.5;
}
geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
geo.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

const mat = new THREE.ShaderMaterial({
  uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color('#a78bfa') } },
  vertexShader: `
    attribute float size;
    uniform float uTime;
    void main() {
      vec3 pos = position;
      pos.y += sin(uTime * 0.3 + position.x * 0.05) * 2.0;
      pos.x += cos(uTime * 0.2 + position.z * 0.04) * 1.5;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
      gl_PointSize = size * (200.0 / -gl_Position.z);
    }
  `,
  fragmentShader: `
    uniform vec3 uColor;
    void main() {
      float dist = length(gl_PointCoord - vec2(0.5));
      if (dist > 0.5) discard;
      float alpha = 1.0 - dist * 2.0;
      gl_FragColor = vec4(uColor, alpha * 0.7);
    }
  `,
  transparent: true, depthWrite: false,
});
scene.add(new THREE.Points(geo, mat));

let t = 0;
(function animate() {
  requestAnimationFrame(animate);
  t += 0.01;
  mat.uniforms.uTime.value = t;
  scene.rotation.y = t * 0.03;
  renderer.render(scene, camera);
})();
window.addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
</script>
</body>
</html>
```

Key decisions:
- COUNT scales with viewport so mobile never chokes  
- ShaderMaterial vertex shader adds sinusoidal drift — looks organic without physics
- `depthWrite: false` prevents z-fighting with overlapping particles
- `min(devicePixelRatio, 2)` caps retina — no need to render at 3× on Pro Max""",
    },
    {
        "q": "What's the best way to do scroll-linked animations with GSAP ScrollTrigger for a premium website feel?",
        "a": """GSAP ScrollTrigger is the industry standard. Here's the pattern I use for every client site — pinned sections, staggered reveals, and a horizontal scroll gallery:

```html
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', sans-serif; background: #0a0a0f; color: #fff; }
  section { min-height: 100vh; display: flex; align-items: center;
            justify-content: center; padding: 4rem; }
  .reveal-block { opacity: 0; transform: translateY(60px); }
  .stat { font-size: clamp(3rem, 8vw, 7rem); font-weight: 800;
          background: linear-gradient(135deg, #fff, #7c3aed);
          -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  /* horizontal gallery */
  .h-scroll-wrap { overflow: hidden; width: 100%; }
  .h-scroll-track { display: flex; gap: 2rem; width: max-content; padding: 2rem; }
  .card { width: 360px; height: 480px; border-radius: 1.5rem;
          background: linear-gradient(135deg, #1e1e3f, #7c3aed40);
          border: 1px solid rgba(124,58,237,0.3); flex-shrink: 0;
          display: flex; align-items: center; justify-content: center;
          font-size: 1.5rem; font-weight: 600; }
</style>
</head>
<body>
<section id="hero">
  <div class="reveal-block" id="hero-text">
    <h1 style="font-size:clamp(3rem,8vw,6rem); font-weight:800">We Build<br>The Future</h1>
  </div>
</section>

<section id="stats" style="flex-direction:column; gap:2rem">
  <div class="stat" id="stat1">0</div>
  <p style="opacity:0.5">clients served worldwide</p>
</section>

<!-- Horizontal scroll gallery — pinned with ScrollTrigger -->
<section id="gallery-section" style="padding:0; overflow:hidden; height:100vh">
  <div class="h-scroll-wrap" id="gallery-wrap">
    <div class="h-scroll-track" id="gallery-track">
      <div class="card">Project One</div>
      <div class="card">Project Two</div>
      <div class="card">Project Three</div>
      <div class="card">Project Four</div>
      <div class="card">Project Five</div>
    </div>
  </div>
</section>

<script src="https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/ScrollTrigger.min.js"></script>
<script>
gsap.registerPlugin(ScrollTrigger);

// 1. Staggered reveal on enter
gsap.to('.reveal-block', {
  opacity: 1, y: 0, duration: 1, ease: 'power3.out',
  scrollTrigger: { trigger: '.reveal-block', start: 'top 80%', once: true }
});

// 2. Counter animation
ScrollTrigger.create({
  trigger: '#stats', start: 'top 60%', once: true,
  onEnter: () => gsap.to({ val: 0 }, {
    val: 847, duration: 2, ease: 'power2.out',
    onUpdate: function() {
      document.getElementById('stat1').textContent = Math.floor(this.targets()[0].val);
    }
  })
});

// 3. Horizontal scroll gallery — pinned
const track = document.getElementById('gallery-track');
const totalScroll = track.scrollWidth - window.innerWidth;
gsap.to(track, {
  x: -totalScroll,
  ease: 'none',
  scrollTrigger: {
    trigger: '#gallery-section',
    start: 'top top',
    end: () => `+=${totalScroll}`,
    pin: true,
    scrub: 1.2,  // scrub > 1 = smoother, lag behind cursor slightly
    invalidateOnRefresh: true,
  }
});
</script>
</body>
</html>
```

The `scrub: 1.2` on horizontal scroll is the secret — values 1–2 feel silky. Never use `scrub: true` (jerky). The `invalidateOnRefresh: true` recalculates on resize so it doesn't break on mobile orientation change.""",
    },
    {
        "q": "How do I create a WebGL animated gradient background like the ones on Linear.app or Stripe's site?",
        "a": """This uses a simple fragment shader with noise to create smooth, organic gradient animations — no Three.js needed, just raw WebGL:

```html
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { overflow: hidden; }
  canvas { position: fixed; inset: 0; width: 100%; height: 100%; }
  .content {
    position: fixed; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; color: #fff;
    font-family: 'Inter', sans-serif; font-size: clamp(2rem,5vw,4rem); font-weight:700;
    text-shadow: 0 2px 20px rgba(0,0,0,.3);
  }
</style>
</head>
<body>
<canvas id="gl"></canvas>
<div class="content"><h1>Premium Experience</h1></div>
<script>
const canvas = document.getElementById('gl');
const gl = canvas.getContext('webgl');

const vert = `
  attribute vec2 a_pos;
  void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
`;

const frag = `
  precision highp float;
  uniform float u_time;
  uniform vec2  u_res;

  // Smooth noise
  vec3 mod289(vec3 x) { return x - floor(x*(1./289.))*289.; }
  vec2 mod289(vec2 x) { return x - floor(x*(1./289.))*289.; }
  vec3 permute(vec3 x) { return mod289((x*34.+1.)*x); }
  float snoise(vec2 v) {
    const vec4 C = vec4(0.211324865405187, 0.366025403784439,
                       -0.577350269189626, 0.024390243902439);
    vec2 i = floor(v + dot(v, C.yy));
    vec2 x0 = v - i + dot(i, C.xx);
    vec2 i1 = (x0.x > x0.y) ? vec2(1.,0.) : vec2(0.,1.);
    vec4 x12 = x0.xyxy + C.xxzz;
    x12.xy -= i1;
    i = mod289(i);
    vec3 p = permute(permute(i.y+vec3(0.,i1.y,1.))+i.x+vec3(0.,i1.x,1.));
    vec3 m = max(0.5-vec3(dot(x0,x0),dot(x12.xy,x12.xy),dot(x12.zw,x12.zw)),0.);
    m = m*m; m = m*m;
    vec3 x = 2.*fract(p*C.www)-1.;
    vec3 h = abs(x)-.5;
    vec3 ox = floor(x+.5);
    vec3 a0 = x - ox;
    m *= 1.79284291400159-.85373472095314*(a0*a0+h*h);
    vec3 g;
    g.x = a0.x*x0.x+h.x*x0.y;
    g.yz = a0.yz*x12.xz+h.yz*x12.yw;
    return 130.*dot(m,g);
  }

  // Brand color palette — swap these to match any brand
  vec3 colorA = vec3(0.04, 0.02, 0.18);  // deep navy
  vec3 colorB = vec3(0.36, 0.10, 0.78);  // purple
  vec3 colorC = vec3(0.06, 0.47, 0.98);  // electric blue
  vec3 colorD = vec3(0.55, 0.15, 0.90);  // violet

  void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    float t = u_time * 0.15;
    // Layer 3 noise octaves for depth
    float n1 = snoise(uv * 2.0 + vec2(t, t * 0.7));
    float n2 = snoise(uv * 4.0 - vec2(t * 0.8, t * 1.2)) * 0.5;
    float n3 = snoise(uv * 8.0 + vec2(t * 1.5, -t)) * 0.25;
    float noise = n1 + n2 + n3;
    // Mix colors using noise threshold
    vec3 col = mix(colorA, colorB, smoothstep(-0.5, 0.5, noise));
    col = mix(col, colorC, smoothstep(0.2, 0.8, uv.x + noise * 0.3));
    col = mix(col, colorD, smoothstep(0.6, 1.0, uv.y + noise * 0.2));
    gl_FragColor = vec4(col, 1.0);
  }
`;

function compile(type, src) {
  const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s;
}
const prog = gl.createProgram();
gl.attachShader(prog, compile(gl.VERTEX_SHADER, vert));
gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, frag));
gl.linkProgram(prog); gl.useProgram(prog);
const buf = gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER, buf);
gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);
const pos = gl.getAttribLocation(prog, 'a_pos');
gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);
gl.enableVertexAttribArray(pos);
const uTime = gl.getUniformLocation(prog, 'u_time');
const uRes  = gl.getUniformLocation(prog, 'u_res');
function resize() {
  canvas.width = innerWidth; canvas.height = innerHeight;
  gl.viewport(0, 0, innerWidth, innerHeight);
}
resize();
window.addEventListener('resize', resize);
let t0 = performance.now();
(function frame() {
  requestAnimationFrame(frame);
  gl.uniform1f(uTime, (performance.now() - t0) / 1000);
  gl.uniform2f(uRes, canvas.width, canvas.height);
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
})();
</script>
</body>
</html>
```

Change `colorA` through `colorD` to match any brand. The 3-octave noise gives it depth — Linear uses 2, Stripe uses 3. Keep `u_time * 0.15` slow for premium; speed up for energy/startup vibes.""",
    },
    {
        "q": "How do I build CSS 3D perspective card flips with tilt-on-hover for a portfolio/case study grid?",
        "a": """Pure CSS 3D for the flip + a tiny JS mousemove tilt effect. No libraries needed:

```html
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#0a0a0f; font-family:'Inter',sans-serif;
         display:flex; flex-wrap:wrap; gap:2rem;
         padding:4rem; justify-content:center; align-items:flex-start; }

  .card-scene {
    width: 340px; height: 440px;
    perspective: 1000px;
    cursor: pointer;
  }
  .card-3d {
    width:100%; height:100%;
    position: relative;
    transform-style: preserve-3d;
    transition: transform 0.7s cubic-bezier(.25,.8,.25,1);
    /* tilt applied via JS inline style */
  }
  .card-scene:hover .card-3d { transform: rotateY(180deg); }
  .card-face {
    position: absolute; inset: 0;
    border-radius: 1.25rem;
    backface-visibility: hidden;
    overflow: hidden;
    display: flex; flex-direction: column;
    justify-content: flex-end; padding: 2rem;
  }
  .card-front {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    border: 1px solid rgba(255,255,255,.08);
  }
  .card-back {
    background: linear-gradient(135deg, #0f3460, #533483);
    transform: rotateY(180deg);
    border: 1px solid rgba(255,255,255,.15);
    gap: 1rem;
  }
  .card-tag { font-size:.75rem; letter-spacing:.12em; text-transform:uppercase;
              color:rgba(255,255,255,.4); margin-bottom:.5rem; }
  .card-title { font-size:1.5rem; font-weight:700; color:#fff; line-height:1.3; }
  .card-desc { color:rgba(255,255,255,.7); font-size:.9rem; line-height:1.6; }
  .card-cta { display:inline-flex; align-items:center; gap:.5rem;
              color:#fff; font-weight:600; font-size:.9rem; margin-top:auto;
              background:rgba(255,255,255,.12); padding:.75rem 1.25rem;
              border-radius:.75rem; width:fit-content; transition:background .2s; }
  .card-cta:hover { background:rgba(255,255,255,.2); }
  /* Accent gradient bar on front */
  .card-accent { position:absolute; top:0; left:0; right:0; height:4px;
                 background:linear-gradient(90deg, #7c3aed, #3b82f6); }
</style>
</head>
<body>

<div class="card-scene" id="card1">
  <div class="card-3d" id="card1-inner">
    <div class="card-face card-front">
      <div class="card-accent"></div>
      <div class="card-tag">Case Study · 2025</div>
      <div class="card-title">IBDS Enterprise<br>AI Dashboard</div>
    </div>
    <div class="card-face card-back">
      <div class="card-tag">Innovation Dev Solutions</div>
      <div class="card-title">AI-Powered<br>Operations</div>
      <div class="card-desc">Multi-agent orchestration system with real-time monitoring, GSD task management, and LangGraph state machine routing.</div>
      <a class="card-cta" href="#">View Case Study →</a>
    </div>
  </div>
</div>

<script>
// Magnetic tilt on hover — applies transform rotation based on mouse position
document.querySelectorAll('.card-scene').forEach(scene => {
  const inner = scene.querySelector('.card-3d');
  let isFlipped = false;

  scene.addEventListener('click', () => { isFlipped = !isFlipped; });

  scene.addEventListener('mousemove', (e) => {
    if (isFlipped) return; // don't tilt when flipped
    const rect = scene.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width  - 0.5;  // -0.5 to 0.5
    const y = (e.clientY - rect.top)  / rect.height - 0.5;
    inner.style.transform = `rotateY(${x * 15}deg) rotateX(${-y * 12}deg)`;
  });

  scene.addEventListener('mouseleave', () => {
    if (isFlipped) return;
    inner.style.transform = '';
    inner.style.transition = 'transform 0.5s ease';
  });

  scene.addEventListener('mouseenter', () => {
    inner.style.transition = 'transform 0.1s ease';
  });
});
</script>
</body>
</html>
```

Key: `perspective: 1000px` on the PARENT, `transform-style: preserve-3d` on the child. Don't put perspective on the same element you're rotating — that's the #1 beginner mistake. The tilt mousemove uses 15° horizontal / 12° vertical which feels natural without being nauseating.""",
    },
    {
        "q": "How do I implement smooth scroll with Lenis and pair it with GSAP ScrollTrigger?",
        "a": """Lenis is the current gold standard for smooth scroll — it smooths out native scroll events and wires perfectly into GSAP's RAF loop:

```html
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:'Inter',sans-serif; background:#050510; color:#fff; }
  section {
    min-height: 100vh; padding: 8rem 4rem;
    display: flex; align-items: center; justify-content: center;
    flex-direction: column; gap: 2rem;
  }
  h2 { font-size: clamp(3rem,6vw,5rem); font-weight:800; text-align:center;
       background: linear-gradient(135deg,#fff,#818cf8);
       -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
  .panel { width:100%; max-width:900px; padding:3rem;
           background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08);
           border-radius:1.5rem; }
</style>
</head>
<body>
<section><h2>Section One</h2><div class="panel reveal"><p>Content that reveals on scroll.</p></div></section>
<section><h2>Section Two</h2><div class="panel reveal"><p>More content here.</p></div></section>
<section><h2>Section Three</h2><div class="panel reveal"><p>Last section.</p></div></section>

<script src="https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/ScrollTrigger.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@studio-freight/lenis@1.0.42/dist/lenis.min.js"></script>
<script>
gsap.registerPlugin(ScrollTrigger);

// 1. Init Lenis
const lenis = new Lenis({
  duration: 1.4,        // scroll duration multiplier — 1.2–1.6 is premium
  easing: t => Math.min(1, 1.001 - Math.pow(2, -10 * t)),  // exponential ease
  smooth: true,
  smoothTouch: false,   // disabled on touch — let native handle it
});

// 2. Wire Lenis into GSAP's RAF — critical step most tutorials skip
lenis.on('scroll', ScrollTrigger.update);
gsap.ticker.add((time) => { lenis.raf(time * 1000); });
gsap.ticker.lagSmoothing(0);  // prevent GSAP lag smoothing from fighting Lenis

// 3. Normal ScrollTrigger animations work as usual
gsap.utils.toArray('.reveal').forEach(el => {
  gsap.fromTo(el,
    { opacity: 0, y: 50 },
    {
      opacity: 1, y: 0, duration: 1, ease: 'power3.out',
      scrollTrigger: {
        trigger: el, start: 'top 80%', once: true,
        // markers: true,  // uncomment to debug
      }
    }
  );
});
</script>
</body>
</html>
```

The wire-up `lenis.on('scroll', ScrollTrigger.update)` + `gsap.ticker.add` is the crucial part. Without it, ScrollTrigger triggers fire at wrong positions with Lenis active. `lagSmoothing(0)` prevents the GSAP lag smoothing from fighting Lenis's smoothing.""",
    },
    {
        "q": "How do I build a CSS-only 3D product showcase with depth layers and parallax on mouse move?",
        "a": """Pure CSS + vanilla JS parallax layers. No Three.js, no libraries — works in all browsers:

```html
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#08080f; font-family:'Inter',sans-serif;
         height:100vh; overflow:hidden; display:flex;
         align-items:center; justify-content:center; }

  .scene {
    position: relative; width:600px; height:600px;
    transform-style: preserve-3d;
    perspective: 800px;
  }
  /* Each layer has a different translateZ and moves at different speed */
  .layer {
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    transform-style: preserve-3d;
    transition: transform 0.1s ease-out; /* smooth after mouse stops */
  }
  .bg-orb {
    width:400px; height:400px; border-radius:50%;
    background: radial-gradient(circle, #7c3aed44 0%, transparent 70%);
    transform: translateZ(-80px);
    filter: blur(40px);
  }
  .ring {
    width:350px; height:350px; border-radius:50%;
    border: 1px solid rgba(124,58,237,.3);
    transform: translateZ(-40px);
  }
  .ring2 {
    width:260px; height:260px; border-radius:50%;
    border: 1px solid rgba(59,130,246,.4);
    transform: translateZ(0px);
  }
  .product-card {
    width:220px; padding:2rem;
    background: rgba(255,255,255,.05);
    border:1px solid rgba(255,255,255,.12);
    border-radius:1.5rem;
    transform: translateZ(40px);
    backdrop-filter: blur(20px);
    text-align:center; color:#fff;
  }
  .product-icon {
    font-size:3rem; margin-bottom:1rem;
    filter: drop-shadow(0 4px 24px rgba(124,58,237,.6));
  }
  .floating-badge {
    position:absolute; top:30px; right:80px;
    background:linear-gradient(135deg,#7c3aed,#3b82f6);
    color:#fff; font-size:.75rem; font-weight:700;
    padding:.4rem 1rem; border-radius:2rem;
    transform: translateZ(80px);
    letter-spacing:.05em;
  }
</style>
</head>
<body>
<div class="scene" id="scene">
  <div class="layer" data-depth="0.2"><div class="bg-orb"></div></div>
  <div class="layer" data-depth="0.4"><div class="ring"></div></div>
  <div class="layer" data-depth="0.6"><div class="ring2"></div></div>
  <div class="layer" data-depth="1.0">
    <div class="product-card">
      <div class="product-icon">⬡</div>
      <h3 style="font-size:1.1rem;font-weight:700;margin-bottom:.5rem">Agentop Pro</h3>
      <p style="font-size:.85rem;opacity:.6">Multi-agent orchestration at enterprise scale</p>
    </div>
  </div>
  <div class="layer" data-depth="1.4"><div class="floating-badge">NEW v2.0</div></div>
</div>

<script>
const scene = document.getElementById('scene');
const layers = scene.querySelectorAll('.layer');
const MAX_TILT = 18; // degrees

document.addEventListener('mousemove', (e) => {
  const cx = innerWidth / 2, cy = innerHeight / 2;
  const dx = (e.clientX - cx) / cx;  // -1 to 1
  const dy = (e.clientY - cy) / cy;

  layers.forEach(layer => {
    const depth = parseFloat(layer.dataset.depth);
    const tx = dx * MAX_TILT * depth;
    const ty = -dy * MAX_TILT * depth;
    layer.style.transform = `rotateY(${tx}deg) rotateX(${ty}deg)`;
  });
  // Counter-rotate scene for a "following" feel
  scene.style.transform = `rotateY(${dx * -3}deg) rotateX(${dy * 3}deg)`;
});

document.addEventListener('mouseleave', () => {
  layers.forEach(l => l.style.transform = '');
  scene.style.transform = '';
});
</script>
</body>
</html>
```

`data-depth` multiplier is the key — deeper layers (translateZ negative) move less (depth 0.2), floating elements (translateZ positive) move more (depth 1.4). This creates genuine parallax depth without Three.js.""",
    },
    {
        "q": "How do I add a canvas ASCII art / generative text background like the one on Vercel's homepage?",
        "a": """This renders a live canvas grid of characters that react to mouse position — it's the \"hacker aesthetic\" effect used on Vercel, GitHub Copilot landing pages, and many SaaS sites:

```html
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#000; overflow:hidden; }
  canvas { position:fixed; inset:0; }
  .overlay {
    position:fixed; inset:0; display:flex; align-items:center; justify-content:center;
    flex-direction:column; gap:1.5rem; pointer-events:none;
    background: radial-gradient(circle at center, transparent 30%, #000 80%);
  }
  h1 { font-family:'Inter',sans-serif; font-size:clamp(3rem,7vw,6rem);
       font-weight:800; color:#fff; text-align:center; }
</style>
</head>
<body>
<canvas id="c"></canvas>
<div class="overlay"><h1>Build the<br>Impossible</h1></div>
<script>
const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const CHARS = '01アイウエオ#$%@&*░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτ';
const FONT_SIZE = 14;
let cols, rows, grid, mouse = { x: 0, y: 0 };

function init() {
  canvas.width  = innerWidth;
  canvas.height = innerHeight;
  cols = Math.ceil(innerWidth  / FONT_SIZE);
  rows = Math.ceil(innerHeight / FONT_SIZE);
  grid = Array.from({ length: rows }, () =>
    Array.from({ length: cols }, () => ({
      char:  CHARS[Math.floor(Math.random() * CHARS.length)],
      time:  Math.random() * 100,
      speed: 0.3 + Math.random() * 0.7,
    }))
  );
}
init();
window.addEventListener('resize', init);
document.addEventListener('mousemove', e => { mouse.x = e.clientX; mouse.y = e.clientY; });

let frame = 0;
(function render() {
  requestAnimationFrame(render);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.font = `${FONT_SIZE}px monospace`;

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const cell = grid[r][c];
      cell.time += cell.speed;
      // Swap char occasionally
      if (Math.random() < 0.002) {
        cell.char = CHARS[Math.floor(Math.random() * CHARS.length)];
      }
      // Distance from mouse cursor drives brightness
      const px = c * FONT_SIZE, py = r * FONT_SIZE;
      const dist = Math.hypot(px - mouse.x, py - mouse.y);
      const bright = Math.max(0.03, 1 - dist / 360);
      // Pulse effect
      const pulse = (Math.sin(cell.time * 0.05) + 1) * 0.5;
      const alpha = bright * (0.15 + pulse * 0.25);
      // Colorize near cursor: green far, cyan close
      const g = Math.floor(200 + bright * 55);
      const b = Math.floor(bright * 200);
      ctx.fillStyle = `rgba(0,${g},${b},${alpha})`;
      ctx.fillText(cell.char, px, py + FONT_SIZE);
    }
  }
  frame++;
})();
</script>
</body>
</html>
```

The `dist / 360` falloff radius controls how wide the glow spreads from the cursor — increase to 500+ for a larger spotlight. `CHARS` mixing Latin digits + Katakana + box-drawing characters gives it the right density without looking like just random letters.""",
    },
    {
        "q": "What's the pattern for a full-page scroll-snapping 3D transition between sections like Zara or Apple?",
        "a": """CSS scroll-snap + CSS 3D transforms + IntersectionObserver. No GSAP needed for this pattern:

```html
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html { scroll-snap-type: y mandatory; overflow-y: scroll; height: 100%; }
  body { height: 100%; font-family:'Inter',sans-serif; }

  section {
    height: 100vh;
    scroll-snap-align: start;
    scroll-snap-stop: always;
    display: flex; align-items: center; justify-content: center;
    overflow: hidden; position: relative;
  }
  /* 3D slide content */
  .slide-content {
    text-align: center; padding: 2rem;
    opacity: 0;
    transform: perspective(800px) rotateX(25deg) translateY(60px);
    transition: opacity 0.9s cubic-bezier(.22,1,.36,1),
                transform 0.9s cubic-bezier(.22,1,.36,1);
  }
  section.in-view .slide-content {
    opacity: 1;
    transform: perspective(800px) rotateX(0deg) translateY(0);
  }
  h2 { font-size: clamp(3rem,8vw,6rem); font-weight:800; line-height:1.1; }
  p  { font-size: 1.1rem; opacity:.7; max-width:500px; margin:.75rem auto 0; }

  /* Individual section themes */
  .s1 { background: linear-gradient(160deg, #0a0a0f 0%, #1a0533 100%); color:#fff; }
  .s2 { background: linear-gradient(160deg, #0f0f0a 0%, #2d1a00 100%); color:#fff; }
  .s3 { background: linear-gradient(160deg, #000d1a 0%, #002966 100%); color:#fff; }
  .s4 { background: #fff; color: #080808; }

  /* Floating orb decorations */
  .orb {
    position:absolute; border-radius:50%; filter:blur(80px);
    pointer-events:none; opacity:.4;
  }
</style>
</head>
<body>

<section class="s1" id="s1">
  <div class="orb" style="width:600px;height:600px;background:#7c3aed;top:-200px;right:-200px"></div>
  <div class="slide-content">
    <h2>Vision</h2>
    <p>The future of work, automated.</p>
  </div>
</section>

<section class="s2" id="s2">
  <div class="orb" style="width:500px;height:500px;background:#f59e0b;bottom:-200px;left:-100px"></div>
  <div class="slide-content">
    <h2>Build</h2>
    <p>Infrastructure that thinks for itself.</p>
  </div>
</section>

<section class="s3" id="s3">
  <div class="orb" style="width:700px;height:700px;background:#3b82f6;top:-300px;left:-200px"></div>
  <div class="slide-content">
    <h2>Scale</h2>
    <p>Enterprise-grade from day one.</p>
  </div>
</section>

<section class="s4" id="s4">
  <div class="slide-content">
    <h2 style="color:#080808">Get Started</h2>
    <p>Schedule your executive consultation today.</p>
    <a href="#" style="display:inline-block;margin-top:2rem;padding:1rem 2.5rem;background:#080808;color:#fff;border-radius:3rem;font-weight:600;font-size:1rem;text-decoration:none">
      Book a Call →
    </a>
  </div>
</section>

<script>
const observer = new IntersectionObserver(
  (entries) => entries.forEach(e => e.target.classList.toggle('in-view', e.isIntersecting)),
  { threshold: 0.5 }  // 50% visible triggers — prevents premature fire
);
document.querySelectorAll('section').forEach(s => observer.observe(s));
</script>
</body>
</html>
```

`scroll-snap-stop: always` prevents fast-scrolling through multiple sections — Apple does this on the iPhone Pro pages. The `perspective(800px) rotateX(25deg)` start state creates that "coming up from below" Apple reveal. Lower threshold to 0.3 if sections feel late to trigger.""",
    },
]


# ── text extraction ────────────────────────────────────────────────────────────

def _read_pdf(path: Path) -> str:
    if not PDF_AVAILABLE:
        return ""
    try:
        reader = _PdfReader(str(path))  # type: ignore[misc]
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _read_pdf(path)
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def iter_files(dirs: list[Path]) -> Iterator[Path]:
    """Yield text files from dirs, respecting SKIP_DIRS + TEXT_EXTS."""
    seen: set[Path] = set()
    for root in dirs:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            # skip dirs in path
            if any(skip in path.parts for skip in SKIP_DIRS):
                continue
            if path.suffix.lower() not in TEXT_EXTS and path.suffix.lower() != ".pdf":
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield path


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks of ~CHUNK_SIZE chars."""
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ── Claude API ─────────────────────────────────────────────────────────────────

def generate_pairs(
    client: Any,
    chunk: str,
    domain: str,
    model: str,
) -> list[dict]:
    """Call Claude with a chunk, return list of {q, a} dicts."""
    system = SYSTEM_PROMPTS.get(domain, SYSTEM_PROMPTS["all"])
    user_msg = f"<source_material>\n{chunk[:3500]}\n</source_material>\n\nGenerate training Q&A pairs from the material above."
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
            temperature=0.7,
        )
        raw = resp.content[0].text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        pairs = json.loads(raw)
        if isinstance(pairs, list):
            return [p for p in pairs if isinstance(p, dict) and "q" in p and "a" in p]
    except Exception as e:
        print(f"  [WARN] API/parse error: {e}", file=sys.stderr)
    return []


def pair_to_sharegpt(q: str, a: str) -> dict:
    return {"conversations": [{"from": "human", "value": q}, {"from": "gpt", "value": a}]}


def generate_pairs_ollama(chunk: str, domain: str) -> list[dict]:
    """Call local Ollama — no API key needed. Returns list of {q, a} dicts."""
    try:
        import requests
    except ImportError:
        return []
    system = SYSTEM_PROMPTS.get(domain, SYSTEM_PROMPTS["all"])
    user_msg = (
        f"<source_material>\n{chunk[:3500]}\n</source_material>\n\n"
        'Generate 4-6 training Q&A pairs. Reply ONLY with a JSON array of {"q": "...", "a": "..."} objects.'
    )
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 2048},
    }
    raw = ""
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=180)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        if isinstance(data, list):
            return [p for p in data if isinstance(p, dict) and "q" in p and "a" in p]
    except json.JSONDecodeError:
        matches = re.findall(r'"q"\s*:\s*"(.+?)"\s*,\s*"a"\s*:\s*"(.+?)"', raw, re.DOTALL)
        return [{"q": q.replace('\\"', '"'), "a": a.replace('\\"', '"')} for q, a in matches[:6]]
    except Exception as e:
        print(f"[WARN] Ollama: {e}", file=sys.stderr)
    return []


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthesize ShareGPT fine-tuning pairs from local sources."
    )
    parser.add_argument(
        "--sources", nargs="+", type=Path, default=[],
        help="Extra source directories to scan (e.g. /mnt/c/Users/Lex/NJIT)",
    )
    parser.add_argument(
        "--domain",
        choices=list(DOMAIN_DIRS.keys()),
        default="agentop",
        help="Domain preset that controls system prompt and source dirs",
    )
    parser.add_argument(
        "--model",
        choices=list(MODELS.keys()),
        default="sonnet",
        help="Claude model to use (haiku=fast, sonnet=balanced, opus=best)",
    )
    parser.add_argument(
        "--budget", type=int, default=200,
        help="Max number of API calls (1 call = 1 chunk). --budget 0 = unlimited",
    )
    parser.add_argument(
        "--seeds-only", action="store_true",
        help="Only output the curated 3D-web seed pairs (no API calls)",
    )
    parser.add_argument(
        "--backend",
        choices=["claude", "ollama", "auto"],
        default="auto",
        help="LLM backend: auto = Claude if ANTHROPIC_API_KEY is set, else Ollama (no key needed)",
    )
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    backend = args.backend
    if backend == "auto":
        backend = "claude" if (api_key and ANTHROPIC_AVAILABLE) else "ollama"

    if backend == "claude" and (not api_key or not ANTHROPIC_AVAILABLE):
        print("Error: --backend claude requires ANTHROPIC_API_KEY and 'pip install anthropic'")
        sys.exit(1)

    if not args.seeds_only and args.domain != "3d-web":
        if backend == "ollama":
            print(f"[info] Ollama backend ({OLLAMA_MODEL} @ {OLLAMA_URL}) — no API key needed")
        else:
            print(f"[info] Claude backend (model: {args.model})")

    client = _anthropic.Anthropic(api_key=api_key) if (backend == "claude" and _anthropic) else None
    model_id = MODELS[args.model]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"{args.domain}_{timestamp}.jsonl"

    all_pairs: list[dict] = []

    # 1. Curated 3D seeds — always include for 3d-web domain
    if args.domain in ("3d-web", "all"):
        print(f"[seed] Injecting {len(THREE_D_WEB_SEEDS)} curated 3D-web pairs")
        for seed in THREE_D_WEB_SEEDS:
            all_pairs.append(pair_to_sharegpt(seed["q"], seed["a"]))

    if args.seeds_only:
        pass  # skip API synthesis

    else:
        # 2. Build source directory list
        scan_dirs: list[Path] = []
        for rel in DOMAIN_DIRS.get(args.domain, []):
            p = ROOT / rel
            if p.exists():
                scan_dirs.append(p)
            else:
                print(f"  [skip] Not found: {p}", file=sys.stderr)

        for extra in args.sources:
            if extra.exists():
                scan_dirs.append(extra)
            else:
                print(f"  [warn] Source path not found: {extra}", file=sys.stderr)

        if not scan_dirs and args.domain != "3d-web":
            print("[warn] No source directories found. Try --sources /path/to/njit")
        
        # 3. Collect chunks
        all_chunks: list[tuple[str, str]] = []  # (source_file, chunk)
        for path in iter_files(scan_dirs):
            text = extract_text(path)
            if not text.strip():
                continue
            chunks = chunk_text(text)
            for ch in chunks:
                all_chunks.append((str(path.relative_to(ROOT)), ch))

        print(f"[info] Found {len(all_chunks)} chunks from {len(scan_dirs)} source dirs")
        
        if args.budget > 0:
            # Cap API calls and sample evenly
            import random
            random.seed(42)
            if len(all_chunks) > args.budget:
                step = len(all_chunks) / args.budget
                all_chunks = [all_chunks[int(i * step)] for i in range(args.budget)]
            print(f"[info] Processing {len(all_chunks)} chunks (budget={args.budget})")

        # 4. Synthesize
        for i, (src_file, chunk) in enumerate(all_chunks):
            print(f"[{i+1:3d}/{len(all_chunks)}] {src_file[:60]}", end="  ", flush=True)
            if backend == "ollama":
                pairs = generate_pairs_ollama(chunk, args.domain)
            elif client:
                pairs = generate_pairs(client, chunk, args.domain, model_id)
            else:
                pairs = []
            print(f"→ {len(pairs)} pairs")
            for p in pairs:
                all_pairs.append(pair_to_sharegpt(p["q"], p["a"]))
            time.sleep(0.15 if backend == "ollama" else 0.3)

    # 5. Write output
    with out_path.open("w", encoding="utf-8") as f:
        for rec in all_pairs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n✓ {len(all_pairs)} training pairs → {out_path}")
    print(f"  Load into Unsloth:  data/training/{out_path.name}")
    print(f"  Combine files:      cat data/training/*.jsonl > data/training/combined.jsonl")


if __name__ == "__main__":
    main()
