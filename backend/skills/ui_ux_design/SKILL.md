# UI/UX Pro Max — Design Intelligence Skill

> Source: [uupm.cc](https://uupm.cc) | 67 UI styles | 161 reasoning rules | 13 framework stacks

## What This Skill Does

Provides production-grade design intelligence for frontend agents building UIs.
Instead of guessing at colors, fonts, layout patterns, or component libraries, agents
query this skill's indexed databases and get ranked results with CSS snippets,
framework-specific code, and accessibility compliance notes.

## Capability Map

| Domain | Database | Records | Usage |
|--------|----------|---------|-------|
| **Styles** | `styles.csv` | 67 | UI aesthetic classification (glassmorphism, brutalism, minimalism, etc.) with CSS keywords and AI prompts |
| **Colors** | `colors.csv` | Per product type | Color palettes organized by industry (SaaS, e-commerce, wellness, portfolio) |
| **Typography** | `typography.csv` | Font pairings | Google Fonts imports with heading/body combos optimized per style |
| **Landing Pages** | `landing.csv` | Layout patterns | Hero-centric, social proof, problem-agitate-solve CTAs |
| **Charts** | `charts.csv` | Chart types | D3, Recharts, Chart.js recommendations per data shape |
| **UX Guidelines** | `ux-guidelines.csv` | Best practices | Anti-patterns, WCAG AA compliance, interaction patterns |
| **Products** | `products.csv` | Product types | SaaS, portfolio, e-commerce — section ordering + CTA strategies |
| **App Interfaces** | `app-interface.csv` | UI patterns | Dashboard, settings, onboarding flows |

## Supported Framework Stacks

| Stack | Tailwind | Component Lib | Notes |
|-------|----------|--------------|-------|
| HTML + Tailwind | Native | — | Default output |
| React | Yes | shadcn/ui | Most production use |
| Next.js | Yes | shadcn/ui | SSR + App Router |
| Vue | Yes | — | Composition API |
| Nuxt | Yes | Nuxt UI | Full-stack Vue |
| Svelte | Yes | — | Lightweight |
| Astro | Yes | — | Content sites |
| React Native | N/A | NativeWind | Mobile |
| Flutter | N/A | Material 3 | Cross-platform |
| SwiftUI | N/A | Native | Apple platforms |
| Jetpack Compose | N/A | Material 3 | Android |

## How Agents Use This Skill

### 1. Design System Generation

When a user says "build me a landing page for a wellness spa", the agent:

1. Queries `products.csv` for "wellness" → gets section ordering, CTA strategy
2. Queries `styles.csv` for matching aesthetic → "Soft UI Evolution" (soft shadows, calming, organic shapes)
3. Queries `colors.csv` → pastel palette with high contrast CTAs
4. Queries `typography.csv` → serif heading + sans-serif body pairing
5. Generates complete design system with tokens, components, and layout

### 2. Component Review

When reviewing frontend PRs, the agent checks:
- Color contrast ratios against WCAG AA
- Font pairing compatibility
- Responsive breakpoint coverage
- Anti-pattern detection (from `ux-guidelines.csv`)

### 3. Style Matching

Given a reference site or description, the agent:
1. Classifies the visual style against the 67 known styles
2. Returns CSS keywords, AI image prompts, and framework-specific implementation

## Search API

```bash
# Domain search
python3 sandbox/ui-ux-pro-max-skill/src/ui-ux-pro-max/scripts/search.py "<query>" --domain <domain>

# Domains: product, style, typography, color, landing, chart, ux
# Stack-specific: --stack react|nextjs|vue|svelte|astro|flutter|swiftui|shadcn
```

## Agent Routing

| Message Pattern | Routes To |
|----------------|-----------|
| "what color palette for SaaS" | knowledge_agent + this skill |
| "review this component's UX" | code_review_agent + this skill |
| "build a landing page for..." | devops_agent + this skill |
| "what font pairs well with Inter" | knowledge_agent + this skill |

## Limitations

- CSV databases are static snapshots (update via `_sync_all.py`)
- No real-time trend data (combine with tech_news cron for trend awareness)
- Framework stacks cover 13 platforms but not all component libraries
