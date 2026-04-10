"""Generate gold training data for the higgsfield_agent.

Produces 700 ShareGPT-format JSONL examples across three categories:
  1. Creative brief → structured production spec (content_type, style, subject, scene_plan, camera, platform_prompt, model_recommendation)
  2. Bad prompt → improved prompt (with explanation of what was wrong)
  3. Rough idea → shot list with lens/camera suggestions

Models known: Diffusion, Mochi, Wan, Kling, Runway Gen-3, Pika, Sora-mini

Usage:
    python -m backend.ml.training.generate_higgsfield_data
    python -m backend.ml.training.generate_higgsfield_data --count 350
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

# ── Model registry ───────────────────────────────────────────────────

_MODELS = [
    {
        "name": "Diffusion",
        "strengths": "photorealistic, detailed textures, slow motion",
        "weaknesses": "long generation time, limited motion range",
        "best_for": ["product shots", "cinematic", "portraits"],
    },
    {
        "name": "Mochi",
        "strengths": "stylized, fast, good with characters",
        "weaknesses": "less photorealistic, shorter clips",
        "best_for": ["character animation", "social media", "explainers"],
    },
    {
        "name": "Wan",
        "strengths": "diverse styles, good composition, medium speed",
        "weaknesses": "sometimes inconsistent across frames",
        "best_for": ["ads", "storytelling", "mixed media"],
    },
    {
        "name": "Kling",
        "strengths": "fast iteration, good motion, affordable",
        "weaknesses": "lower resolution, limited camera control",
        "best_for": ["prototyping", "social clips", "rapid iteration"],
    },
]

_STYLES = [
    "cinematic",
    "noir",
    "documentary",
    "commercial",
    "anime",
    "retro",
    "minimalist",
    "surreal",
    "corporate",
    "vlog",
    "editorial",
    "music video",
    "sci-fi",
    "fantasy",
    "warm + cozy",
    "cold + clinical",
    "neon cyberpunk",
    "vintage film grain",
    "clean modern",
    "hand-drawn feel",
]

_SUBJECTS = [
    "AI receptionist",
    "robot barista",
    "virtual tutor",
    "digital twin",
    "product showcase",
    "brand mascot",
    "tech demo",
    "customer testimonial",
    "architecture walkthrough",
    "nature documentary",
    "food preparation",
    "fitness routine",
    "meditation guide",
    "startup pitch",
    "team introduction",
    "city timelapse",
    "weather visualization",
    "data dashboard come alive",
]

_PLATFORMS = [
    ("Instagram Reels", "9:16", "15-30s", "hook in first 2s, text overlays, trending audio"),
    ("TikTok", "9:16", "15-60s", "fast transitions, captions mandatory, trend-aware"),
    ("YouTube Shorts", "9:16", "15-60s", "story arc, subscribe CTA, creator face optional"),
    ("LinkedIn", "16:9", "30-90s", "professional tone, insight-led, no flashy effects"),
    ("Twitter/X", "16:9", "15-30s", "punchy, controversial or insightful, auto-play friendly"),
    ("Website hero", "16:9", "5-15s", "seamless loop, no audio dependency, fast load"),
    ("Presentation", "16:9", "5-10s", "clean background, supports slide context, no distractions"),
]

_CAMERA_MOVES = [
    "slow dolly forward",
    "static wide shot",
    "close-up rack focus",
    "tracking shot left-to-right",
    "aerial drone pull-back",
    "handheld documentary style",
    "slow zoom out from detail",
    "rotating orbit around subject",
    "tilt up from ground level",
    "push-in to face",
    "static tripod with shallow DOF",
    "crane shot rising",
    "steady glide through scene",
]

_DURATIONS = ["3s", "5s", "10s", "15s", "30s"]

# ── Creative brief templates ─────────────────────────────────────────

_BRIEF_TEMPLATES: list[dict] = [
    {
        "input": "make me a {style} video of {subject}, like {duration}",
        "category": "creative_brief",
        "difficulty": "easy",
    },
    {
        "input": "i need a video ad for {subject}, should feel {style}, gonna post on {platform_name}",
        "category": "creative_brief",
        "difficulty": "medium",
    },
    {
        "input": "create something epic with {character} — {style} vibes, maybe {duration}? use whatever model works best",
        "category": "creative_brief",
        "difficulty": "medium",
    },
    {
        "input": "i want {subject} but make it {style} and {style2}, for {platform_name}. {duration} max",
        "category": "creative_brief",
        "difficulty": "hard",
    },
    {
        "input": "{subject} video, {style}, needs to loop seamlessly for a website hero section",
        "category": "creative_brief",
        "difficulty": "hard",
    },
    {
        "input": "something like a {style} take on {subject}... not sure about duration, maybe short?",
        "category": "creative_brief",
        "difficulty": "easy",
    },
    {
        "input": "promotional video for {subject}. target audience is tech professionals. {platform_name}. premium feel.",
        "category": "creative_brief",
        "difficulty": "hard",
    },
    {"input": "just make {subject} look cool idk", "category": "creative_brief", "difficulty": "easy"},
]

# Bad prompt → improved prompt templates
_BAD_PROMPT_TEMPLATES: list[dict] = [
    {
        "bad": "a person walking",
        "good": "A confident {subject} walking through a modern office lobby with glass walls and warm lighting, shot from a low angle dolly tracking left-to-right, cinematic color grading with teal shadows and amber highlights, 5s",
        "fix": "Added specific subject, environment details, lighting, camera movement, color grading, and duration. Vague prompts produce generic results.",
        "category": "prompt_improvement",
        "difficulty": "easy",
    },
    {
        "bad": "cool robot doing stuff",
        "good": "A sleek humanoid robot with brushed titanium finish performing a precise hand gesture presentation, {style} lighting with volumetric fog, close-up rack focus from hands to face, soft ambient glow, 5s loop",
        "fix": "Replaced vague 'cool' and 'stuff' with specific visual descriptors: material (brushed titanium), action (hand gesture presentation), lighting (volumetric fog), camera (rack focus), and format (loop).",
        "category": "prompt_improvement",
        "difficulty": "medium",
    },
    {
        "bad": "make a video of nature",
        "good": "Golden hour aerial drone pull-back over a misty mountain valley with a winding river, autumn foliage in warm oranges and reds, parallax depth effect with foreground pine trees, {duration}, cinematic 24fps",
        "fix": "Specified time of day (golden hour), camera movement (aerial pull-back), terrain details, color palette, depth technique, duration, and frame rate. 'Nature' alone activates too many unrelated concepts.",
        "category": "prompt_improvement",
        "difficulty": "easy",
    },
    {
        "bad": "ai doing something futuristic",
        "good": "An AI interface materialized as a translucent holographic sphere, rotating slowly in a dark control room with blue edge lighting, data streams flowing across its surface, {style} aesthetic, static wide shot with shallow depth of field, 10s",
        "fix": "Replaced abstract 'AI' with a concrete visual (holographic sphere), added environment (dark control room), motion (rotating, data streams), aesthetic direction, and camera setup.",
        "category": "prompt_improvement",
        "difficulty": "medium",
    },
    {
        "bad": "product video for my app",
        "good": "A smartphone displaying the app interface floats in center frame against a clean white gradient background, UI elements animate in sequence (dashboard → chart → notification), subtle shadow beneath phone, smooth 360° orbit around device, modern {style} lighting, {duration}",
        "fix": "Specified device, background, UI animation sequence, shadow detail, camera movement, and lighting. Product videos need the viewer to see and follow specific elements.",
        "category": "prompt_improvement",
        "difficulty": "hard",
    },
    {
        "bad": "someone talking to camera",
        "good": "A professional {subject} seated in a well-lit studio with soft key light at 45°, subtle hair light, blurred bookshelf background at f/2.8, speaking directly to lens with confident posture, medium close-up from chest up, warm neutral color grade, 30s",
        "fix": "Added lighting setup (key light angle, hair light), background (blurred bookshelf), aperture/DOF, framing (medium close-up), posture direction, and color grade. Talking-head videos live or die on lighting.",
        "category": "prompt_improvement",
        "difficulty": "hard",
    },
]

_CHARACTERS = ["Xpel", "MrWilly", "Dr_Nova", "Agent_K", "ByteBot"]


def _pick_model_for_style(style: str, platform_name: str) -> dict:
    """Select the best model based on style and platform."""
    if "cinematic" in style or "noir" in style or "editorial" in style:
        return _MODELS[0]  # Diffusion
    if "anime" in style or "character" in platform_name.lower():
        return _MODELS[1]  # Mochi
    if "social" in platform_name.lower() or "tiktok" in platform_name.lower():
        return _MODELS[3]  # Kling (fast iteration)
    return random.choice(_MODELS)


def _generate_creative_brief(template: dict) -> dict:
    """Generate one creative brief → spec example."""
    style = random.choice(_STYLES)
    style2 = random.choice([s for s in _STYLES if s != style])
    subject = random.choice(_SUBJECTS)
    platform = random.choice(_PLATFORMS)
    platform_name, aspect, dur_range, platform_notes = platform
    duration = random.choice(_DURATIONS)
    character = random.choice(_CHARACTERS)
    camera = random.choice(_CAMERA_MOVES)
    model = _pick_model_for_style(style, platform_name)

    inp = template["input"]
    inp = inp.replace("{style}", style).replace("{style2}", style2)
    inp = inp.replace("{subject}", subject).replace("{platform_name}", platform_name)
    inp = inp.replace("{duration}", duration).replace("{character}", character)

    # Random messiness
    if random.random() < 0.3:
        inp = inp.lower()
    if random.random() < 0.2:
        inp = random.choice(["hey ", "yo ", "um ", "ok so "]) + inp

    spec = {
        "content_type": "video_ad" if "ad" in inp.lower() or "promotional" in inp.lower() else "creative_video",
        "style": style if "{style2}" not in template["input"] else f"{style} + {style2}",
        "subject": subject,
        "scene_plan": f"Open: {camera} establishing {subject} in context. "
        f"Mid: transition to detail shot highlighting key visual. "
        f"Close: pull back to full composition with platform-optimized framing.",
        "camera": camera,
        "platform_prompt": f"{platform_name} ({aspect}, {dur_range}): {platform_notes}",
        "model_recommendation": f"{model['name']} — {model['strengths']}. Best for: {', '.join(model['best_for'])}.",
        "duration": duration,
        "aspect_ratio": aspect,
    }

    system_msg = (
        "You are the Agentop Higgsfield Video Production Agent in CREATIVE BRIEF mode.\n"
        "Convert rough creative goals into structured production specs.\n"
        "Output JSON with: content_type, style, subject, scene_plan, camera, "
        "platform_prompt, model_recommendation, duration, aspect_ratio.\n"
        "You know every Higgsfield model at expert level."
    )

    return {
        "conversations": [
            {"from": "system", "value": system_msg},
            {"from": "human", "value": inp},
            {"from": "gpt", "value": json.dumps(spec, indent=2)},
        ],
        "metadata": {
            "source": "agentop_higgsfield_gold",
            "category": "creative_brief",
            "style": style,
            "model": model["name"],
            "platform": platform_name,
            "difficulty": template["difficulty"],
        },
    }


def _generate_prompt_improvement(template: dict) -> dict:
    """Generate one bad→good prompt improvement example."""
    style = random.choice(_STYLES)
    subject = random.choice(_SUBJECTS)
    duration = random.choice(_DURATIONS)

    bad = template["bad"]
    good = template["good"].replace("{style}", style).replace("{subject}", subject).replace("{duration}", duration)
    fix = template["fix"]

    system_msg = (
        "You are the Agentop Higgsfield Video Production Agent.\n"
        "Given a weak or vague video prompt, produce an improved version with specific visual details.\n"
        "Explain what was wrong with the original and why each addition matters."
    )

    response = f"**Improved prompt:**\n{good}\n\n**What was fixed:**\n{fix}"

    return {
        "conversations": [
            {"from": "system", "value": system_msg},
            {"from": "human", "value": f'Improve this video prompt: "{bad}"'},
            {"from": "gpt", "value": response},
        ],
        "metadata": {
            "source": "agentop_higgsfield_gold",
            "category": "prompt_improvement",
            "difficulty": template["difficulty"],
        },
    }


def _generate_shot_list() -> dict:
    """Generate a rough idea → shot list example."""
    subject = random.choice(_SUBJECTS)
    style = random.choice(_STYLES)
    platform = random.choice(_PLATFORMS)
    platform_name, aspect, dur_range, _ = platform
    duration = random.choice(["15s", "30s", "60s"])
    model = _pick_model_for_style(style, platform_name)

    rough_ideas = [
        f"i wanna make a {style} thing about {subject} for {platform_name}",
        f"need a video of {subject}, maybe {duration}? not sure about the shots",
        f"{subject} video — make it look professional, posting on {platform_name}",
        f"something with {subject}, {style} feel, give me a shot breakdown",
    ]
    idea = random.choice(rough_ideas)
    if random.random() < 0.3:
        idea = idea.lower()

    # Generate 3-5 shots
    num_shots = random.randint(3, 5)
    shots = []
    cameras = random.sample(_CAMERA_MOVES, min(num_shots, len(_CAMERA_MOVES)))
    shot_types = ["establishing wide", "medium shot", "close-up detail", "reaction/transition", "closing reveal"]
    for i in range(num_shots):
        shots.append(
            {
                "shot": i + 1,
                "type": shot_types[i % len(shot_types)],
                "camera": cameras[i],
                "duration": f"{random.choice([2, 3, 5, 7])}s",
                "description": f"Shot {i + 1}: {shot_types[i % len(shot_types)]} of {subject}",
                "lens_suggestion": random.choice(
                    ["24mm wide", "35mm standard", "50mm portrait", "85mm telephoto", "16mm ultra-wide"]
                ),
            }
        )

    shot_list = {
        "project": f"{style} {subject} for {platform_name}",
        "total_duration": duration,
        "aspect_ratio": aspect,
        "model_recommendation": model["name"],
        "shots": shots,
    }

    system_msg = (
        "You are the Agentop Higgsfield Video Production Agent.\n"
        "Convert rough video ideas into detailed shot lists with lens/camera suggestions.\n"
        "Include shot number, type, camera movement, duration, description, and lens suggestion."
    )

    return {
        "conversations": [
            {"from": "system", "value": system_msg},
            {"from": "human", "value": idea},
            {"from": "gpt", "value": json.dumps(shot_list, indent=2)},
        ],
        "metadata": {
            "source": "agentop_higgsfield_gold",
            "category": "shot_list",
            "style": style,
            "model": model["name"],
            "platform": platform_name,
            "difficulty": "medium",
        },
    }


def generate(count: int = 700, seed: int = 42) -> list[dict]:
    """Generate `count` ShareGPT-format training examples for higgsfield_agent."""
    random.seed(seed)
    examples = []

    # Distribution: 50% creative briefs, 25% prompt improvements, 25% shot lists
    n_briefs = int(count * 0.50)
    n_improvements = int(count * 0.25)
    n_shots = count - n_briefs - n_improvements

    for _ in range(n_briefs):
        template = random.choice(_BRIEF_TEMPLATES)
        examples.append(_generate_creative_brief(template))

    for _ in range(n_improvements):
        template = random.choice(_BAD_PROMPT_TEMPLATES)
        examples.append(_generate_prompt_improvement(template))

    for _ in range(n_shots):
        examples.append(_generate_shot_list())

    random.shuffle(examples)
    return examples


def main() -> None:
    count = 700
    if len(sys.argv) > 1 and sys.argv[1] == "--count":
        count = int(sys.argv[2])

    outdir = Path("data/training/gold")
    outdir.mkdir(parents=True, exist_ok=True)
    outpath = outdir / "higgsfield_agent_v1.jsonl"

    examples = generate(count=count)
    with open(outpath, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    # Stats
    categories: dict[str, int] = {}
    models_used: dict[str, int] = {}
    for ex in examples:
        c = ex["metadata"]["category"]
        categories[c] = categories.get(c, 0) + 1
        m = ex["metadata"].get("model", "n/a")
        models_used[m] = models_used.get(m, 0) + 1

    print(f"Generated {len(examples)} examples → {outpath}")
    print(f"  Categories: {categories}")
    print(f"  Models used: {dict(sorted(models_used.items(), key=lambda x: -x[1]))}")


if __name__ == "__main__":
    main()
