# AI Website Cloner

> Reverse-engineer any live website into a clean, deployable Next.js codebase.

## Purpose
Clone any website by analyzing its visual design, extracting components, and rebuilding them as clean React components with Tailwind CSS. Useful for:
- Learning how production sites are built
- Rapid prototyping from existing designs
- Creating pixel-perfect reproductions for testing
- Portfolio showcase of reverse-engineering capability

## 5-Phase Pipeline

### Phase 1: Reconnaissance
**Goal:** Full visual and structural audit of the target site.

1. Navigate to target URL via `browser_control`
2. Take full-page screenshots at 3 viewports:
   - Desktop: 1440×900
   - Tablet: 768×1024
   - Mobile: 375×812
3. Extract design tokens:
   ```
   browser_control("evaluate", agent_id, code="JSON.stringify({
     fonts: [...new Set([...document.querySelectorAll('*')].map(e => getComputedStyle(e).fontFamily))],
     colors: [...new Set([...document.querySelectorAll('*')].flatMap(e => {
       const s = getComputedStyle(e);
       return [s.color, s.backgroundColor, s.borderColor].filter(c => c !== 'rgba(0, 0, 0, 0)');
     }))],
     favicon: document.querySelector('link[rel*=icon]')?.href
   })")
   ```
4. Map page sections by scrolling and capturing:
   - Header/nav structure
   - Hero section
   - Feature blocks
   - Testimonials/social proof
   - Footer
   - Any modals/overlays
5. Record all interactions (hover states, dropdowns, animations)

**Output:** `docs/research/site_audit.md` with screenshots and token inventory.

### Phase 2: Foundation Build
**Goal:** Set up the Next.js project skeleton with extracted design system.

1. Scaffold project:
   ```bash
   npx create-next-app@latest clone-output --typescript --tailwind --app --src-dir
   ```
2. Install shadcn/ui:
   ```bash
   cd clone-output && npx shadcn@latest init
   ```
3. Update `globals.css` with extracted design tokens (colors → oklch, fonts)
4. Download all referenced assets (images, SVGs, fonts) via:
   ```bash
   wget -P public/assets/ <extracted_urls>
   ```
5. Convert extracted SVG icons to React components in `src/components/icons/`

**Output:** Clean Next.js project with design system configured.

### Phase 3: Component Spec & Dispatch
**Goal:** Create detailed specs for each page section, then build in parallel.

For each section identified in Phase 1:

1. **Extract exact styles** via `browser_control("evaluate")`:
   ```javascript
   // For each section element
   const styles = getComputedStyle(element);
   return {
     padding, margin, fontSize, fontWeight, lineHeight,
     color, backgroundColor, borderRadius, gap, display,
     gridTemplateColumns, flexDirection, maxWidth
   };
   ```

2. **Write component spec** to `docs/research/components/<SectionName>.spec.md`:
   ```markdown
   # HeroSection Component Spec
   ## Layout: flex column, center-aligned, max-w-6xl mx-auto
   ## Typography: h1 text-5xl font-bold, p text-xl text-gray-600
   ## Colors: bg-white, text-gray-900, accent #3B82F6
   ## Responsive: mobile stack → desktop side-by-side
   ## Interactions: CTA button hover scale-105, gradient shift
   ## Content: [exact text extracted]
   ## Assets: hero-image.png (1200x800)
   ```

3. **Build component** as `src/components/<SectionName>.tsx`:
   - Follow spec exactly
   - Use Tailwind classes (no inline styles)
   - Use shadcn/ui primitives where appropriate
   - All images use `next/image` with extracted dimensions

### Phase 4: Page Assembly
**Goal:** Wire all components into the page layout.

1. Create `src/app/page.tsx` importing all section components
2. Wire scroll behaviors (smooth scroll, intersection observers)
3. Add metadata (title, description, OG tags) extracted from original
4. Verify responsive layout at all 3 viewports
5. Add `next.config.js` image domains for external assets

### Phase 5: Visual QA Diff
**Goal:** Pixel-level comparison against original.

1. Run `npm run build && npm start` on the clone
2. Screenshot clone at all 3 viewports
3. Compare side-by-side with Phase 1 screenshots
4. Log discrepancies with severity:
   - **P0:** Layout broken, missing sections
   - **P1:** Wrong colors, fonts, spacing >4px off
   - **P2:** Minor alignment, animation differences
5. Fix P0/P1 issues, accept P2

**Output:** `docs/research/qa_report.md` with comparison screenshots and diff scores.

## Tool Requirements
| Tool | Phase | Purpose |
|------|-------|---------|
| `browser_control` | 1, 3, 5 | Navigate, screenshot, JS evaluation |
| `safe_shell` | 2, 4, 5 | npm commands, asset downloads, build |
| `file_reader` | 3, 4 | Read specs and extracted data |
| `doc_updater` | 1, 3, 5 | Write specs, audit, QA reports |
| `git_ops` | 3 | Branch management for parallel builds |

## Agent Routing
- **Primary:** `devops_agent` — project scaffolding, git management, builds
- **QA:** `code_review_agent` — component review, spec compliance
- **WebGen integration:** Can hand off to `SitePlanner` → `PageGenerator` pipeline for AI-enhanced generation

## Limitations
- Single-page clones work best; multi-page sites need per-page runs
- Dynamic content (API-driven) captured as static snapshots
- Authentication-gated pages need manual login first
- JavaScript-heavy SPAs may need additional browser interaction scripting

## Example Usage
```
User: "Clone https://stripe.com/payments"
→ Phase 1: Recon (screenshots, tokens, sections mapped)
→ Phase 2: Foundation (Next.js + Tailwind + shadcn scaffold)
→ Phase 3: 6 component specs + builds (Hero, Features, Pricing, Integrations, CTA, Footer)
→ Phase 4: Assembly + responsive verification
→ Phase 5: QA diff → 95% visual match
→ Output: ./clone-output/ ready for `npm run dev`
```
