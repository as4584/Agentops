# Sigma Simulator — Game Design Document
**Project Codename:** robloxidea  
**Genre:** Idle Clicker / Simulator  
**Platform:** Roblox  
**Template:** Baseplate  
**Target Audience:** 10–18, brainrot/meme culture fans  
**Session Type:** One-sitting with a friend (co-op + competitive)  
**Status:** V4 — Active Development

---

## Implementation Status

| GDD Feature | Status | Notes |
|-------------|--------|-------|
| Click → Sigma (4-tier crits) | ✅ Live | Normal / NICE / SIGMA! / GIGACHAD!! |
| Rank ladder (12 ranks) | ✅ Live | NPC → THE GOAT |
| Upgrade tree (10 upgrades) | ✅ Live | — |
| Pet system (hatch, equip, evolve) | ✅ Live | — |
| Egg shop (3 eggs, rarity pools) | ✅ Live | Reroll with Rizz Tokens |
| Spin wheel (8 prizes) | ✅ Live | Free spin cooldown |
| Daily rewards (10-day streak) | ✅ Live | — |
| Quests (8 quests) | ✅ Live | — |
| Achievements (12 achievements) | ✅ Live | — |
| Free reward slots (3 timed) | ✅ Live | — |
| Sigma Duels (1v1 click race) | ✅ Live | — |
| Prestige + Ascension | ✅ Live | — |
| God mode flash | ✅ Live | — |
| Leaderboard (top 5) | ✅ Live | — |
| Co-op boost (+20%) | ✅ Live | — |
| Events (6 types, world Parts) | ✅ Live | — |
| Offline earnings (up to 4h) | ✅ Live | — |
| Tap-anywhere + Space key | ✅ Live | No click button |
| Glass morphism nav rail | ✅ Live | Chat 3 |
| Icon + text nav pills | ✅ Live | Chat 3 |
| Sound system (crits, hatch, death) | ✅ Live | Chat 3 |
| Map zones by rank | ❌ Backlog | Chat 4 priority |
| Character aura by prestige | ❌ Backlog | Chat 4 priority |
| Sound mute/toggle button | ❌ Backlog | Chat 4 priority |
| Floating sigma numbers | 🔧 Partial | `spawnFloat` may still be blocked |
| Rank-up fanfare animation | ❌ Backlog | — |
| Map evolution visuals | ❌ Backlog | — |

---

## Table of Contents
1. [Concept Overview](#concept-overview)
2. [Core Loop](#core-loop)
3. [Dopamine Systems](#dopamine-systems)
4. [Progression — Rank Ladder](#progression--rank-ladder)
5. [Currency System](#currency-system)
6. [Click System](#click-system)
7. [Upgrade Tree](#upgrade-tree)
8. [Pet System](#pet-system)
9. [Random Events](#random-events)
10. [Prestige System](#prestige-system)
11. [Social & Co-op Features](#social--co-op-features)
12. [Map Progression](#map-progression)
13. [Daily Engagement Systems](#daily-engagement-systems)
14. [Audio Design](#audio-design)
15. [Folder Structure](#folder-structure)
16. [Launch Roadmap](#launch-roadmap)

---

## Concept Overview

> **Sigma Simulator** is a brainrot-themed idle clicker where players click to earn Sigma Points, buy upgrades, rank up from NPC to THE GOAT, collect meme pets, and flex on their friends on the leaderboard.

The game is designed around:
- Satisfying click feedback
- Always having a next goal visible
- Meme/brainrot humor for viral TikTok/YouTube potential
- Strong co-op hooks to encourage playing with friends

---

## Core Loop

```
Click → Earn Sigma → Buy Upgrade → Bigger Multiplier → Click → Earn More Sigma
  ↑                                                                      |
  └──────────────────── Prestige (reset + permanent bonus) ─────────────┘
```

**Rule:** Every 30 seconds the player should unlock or achieve SOMETHING.  
**Rule:** The player should NEVER feel stuck — always show the next goal greyed out with its cost.

---

## Dopamine Systems

These are the core psychological hooks that keep players engaged:

| System | Dopamine Mechanism |
|--------|--------------------|
| Numbers going up | Core brain satisfaction loop |
| 12-rank ladder | Always a visible next milestone |
| Critical clicks | Unpredictable big reward spikes |
| Pet hatching | Surprise reveal + collection addiction |
| Random events | Unpredictable urgency and excitement |
| Prestige reset | "New game+" feeling, faster progression |
| Friend leaderboard | Social comparison and competition |
| Map evolution | Visual proof of progress |
| Daily quests | Reason to return every day |
| Rank up fanfare | Celebration moment with sound + visuals |

**Key Principle:** Never let the number feel slow. Upgrades should always feel like they meaningfully change the speed of progression.

---

## Progression — Rank Ladder

12 ranks from NPC to THE GOAT. Each rank unlocks new content and cosmetics.

| # | Rank | Sigma Required | Unlock |
|---|------|---------------|--------|
| 1 | 🤡 NPC | 0 | Starting rank, grey map |
| 2 | 😐 Normie | 500 | New click animation |
| 3 | 💪 Gym Bro | 2,000 | First pet slot, gym area on map |
| 4 | 🐺 Lone Wolf | 10,000 | Wolf forest unlocks on map |
| 5 | 😎 Sigma | 50,000 | Aura effect on character |
| 6 | 🗿 Ohio Resident | 150,000 | Ohio portal opens on map |
| 7 | 🔥 Rizzler | 500,000 | Rizz aura + voice sound effect |
| 8 | 👑 Gigachad | 1,000,000 | Gigachad character skin |
| 9 | ⚡ Skibidi God | 5,000,000 | Skibidi dance emote |
| 10 | 🌌 Sigma Multiverse | 25,000,000 | Prestige system unlocks |
| 11 | ☠️ Final Form | 100,000,000 | All cosmetics unlocked |
| 12 | 🏆 THE GOAT | Prestige 5+ | Exclusive GOAT crown, server announcement |

**UI Rule:** Always show the current rank and a progress bar to the next rank on screen at all times.

---

## Currency System

Two currencies — both earnable in-game, no pay-to-win.

### Sigma Points 💠
- Primary currency
- Earned by clicking and idle pets
- Spent on upgrades
- Displayed on the leaderboard

### Rizz Tokens 💎
- Secondary "premium feel" currency — but fully free to earn
- Earned via:
  - Daily login streaks
  - Reaching new ranks
  - Random event rewards
  - Prestige completions
- Spent on:
  - Pet eggs (cosmetic pets)
  - Character skins
  - Special emotes
  - Temporary boost items (not pay-to-win)

---

## Click System

### Click Feel (Visual Feedback)
- Floating number pops up from click point
- Numbers are color-coded by tier (white → yellow → orange → red for crits)
- Screen shake on critical hits
- Click button visually bounces on press
- Combo counter appears when clicking quickly

### Critical Click System
| Type | Chance | Multiplier | Visual |
|------|--------|------------|--------|
| Normal | 70% | 1x | White number |
| Nice | 20% | 2x | Yellow "NICE!" popup |
| Sigma | 8% | 5x | Orange "SIGMA!" popup |
| GIGACHAD | 2% | 20x | Red screen flash + sound |

### Combo System
- Click 5 times within 1 second = Combo active
- Combo multiplies sigma gain by 1.5x while active
- Combo meter visible on screen, drains if you stop clicking
- Rewards fast clickers and keeps sessions active

---

## Upgrade Tree

Upgrades are split into two branching paths, requiring both to unlock the endgame upgrade.

```
                    [Sigma Mindset — 2x click]
                           ↓
            ┌──────────────┴──────────────┐
            ↓                             ↓
    [LONE WOLF PATH]              [GRINDSET PATH]
    Click power focused           Idle/auto focused
            ↓                             ↓
    [Wolf Pack — 10x]         [Passive Income — 5σ/sec]
            ↓                             ↓
    [Alpha Aura — 50x]        [Empire Builder — 25σ/sec]
            └──────────────┬──────────────┘
                           ↓
                  [SIGMA CONVERGENCE]
                  (requires both paths)
                  1000x click + 100σ/sec
```

### Full Upgrade List

| ID | Name | Path | Cost | Effect |
|----|------|------|------|--------|
| 1 | Sigma Mindset | Root | 100 | 2x click |
| 2 | Wolf Pack | Lone Wolf | 500 | 10x click |
| 3 | Alpha Aura | Lone Wolf | 2,000 | 50x click |
| 4 | Passive Income | Grindset | 500 | +5 σ/sec |
| 5 | Empire Builder | Grindset | 2,000 | +25 σ/sec |
| 6 | Lone Wolf Mode | Lone Wolf | 10,000 | 5x click |
| 7 | Grindset Activated | Grindset | 10,000 | 10x click |
| 8 | Gigachad Transformation | Both | 50,000 | 50x click |
| 9 | Final Form Sigma | Both | 50,000 | 100x click |
| 10 | SIGMA CONVERGENCE | Both required | 100,000 | 1000x click + 100σ/sec |

---

## Pet System

Pets are the primary collection mechanic and idle income source. Players LOVE hatching eggs.

### How Pets Work
- Pets auto-collect Sigma Points passively (idle mechanic)
- Player can equip up to 3 pets at once
- Pets follow the player character visually
- Pets can be leveled up (costs Sigma Points)

### Pet Tiers & Auto Income
| Tier | Pet | Auto σ/sec | How to Get |
|------|-----|------------|------------|
| Common | 🐶 NPC Dog | 1/sec | Basic Egg (100 Rizz) |
| Uncommon | 🐺 Lone Wolf | 5/sec | Sigma Egg (250 Rizz) |
| Rare | 🗿 Ohio Cat | 20/sec | Ohio Egg (500 Rizz) |
| Epic | 💪 Gigachad Bird | 100/sec | Gigachad Egg (1000 Rizz) |
| Legendary | 👑 Sigma Dragon | 1000/sec | Legendary Egg (2500 Rizz) |
| Mythic | 🌌 Brainrot God | 10000/sec | Mythic Egg (5000 Rizz) |

### Egg Hatching Flow
1. Player opens egg from inventory
2. Egg shaking animation (2 seconds of anticipation)
3. Big reveal with rarity color flash
4. "YOU GOT A [RARITY] [PET NAME]!" text
5. Pet appears and does a little bounce animation

**Design Note:** The anticipation + reveal is the highest dopamine moment in the game. Make it dramatic.

---

## Random Events

Random events fire every 3–5 minutes to break up the clicking routine and spike engagement.

| Event | Duration | Effect | Trigger |
|-------|----------|--------|---------|
| 🔥 Sigma Rush | 30 sec | 3x all sigma gain | Automatic |
| 🌪️ Ohio Storm | 45 sec | Map goes weird, 2x sigma | Automatic |
| 💎 Rizz Rain | 20 sec | Free Rizz Tokens fall from sky | Automatic |
| 👑 Gigachad Visit | 60 sec | Giant NPC walks by, bonus clicks | Automatic |
| ☠️ NPC Invasion | 30 sec | Click NPCs for bonus sigma | Automatic |
| 🎰 Sigma Lottery | 10 sec | Click the lottery orb fast to win jackpot | Automatic |

### Event Announcement
- Server-wide notification banner drops from top of screen
- Color-coded by event type
- Timer countdown visible during event
- Sound effect plays when event starts

---

## Prestige System

The prestige system is what converts a one-session game into a multi-week game.

### How Prestige Works
1. Reach 25,000,000 Sigma (Rank: Sigma Multiverse)
2. "PRESTIGE" button unlocks at the Sigma HQ building
3. Confirm prestige — resets Sigma Points and upgrades to 0
4. Earn permanent prestige multiplier applied to all future runs
5. New run starts faster due to multiplier — feels rewarding not punishing

### Prestige Reward Table
| Prestige # | Permanent Bonus | Cosmetic Reward |
|-----------|----------------|-----------------|
| 1 | 2x all sigma (permanent) | Gold name tag |
| 2 | 5x all sigma (permanent) | Flame aura |
| 3 | 10x all sigma (permanent) | Rainbow trail |
| 4 | 25x all sigma (permanent) | Custom title badge |
| 5 | 100x all sigma (permanent) | THE GOAT crown (exclusive) |

**Design Note:** Make the prestige animation a big moment — confetti, sound, server announcement. It should feel like an achievement, not a punishment.

---

## Social & Co-op Features

> If playing together is MORE rewarding than playing solo, friends will keep dragging each other back.

### Co-op Bonuses
| Feature | Description |
|---------|-------------|
| Friend Presence Boost | +1.5x sigma just for having a friend in the same server |
| Sigma Sync | Both players click at exact same time = 3x bonus for 5 seconds |
| Shared Events | Random events trigger for both players simultaneously |
| Trade System | Send pets to your friend |
| Team Leaderboard | Combined score vs other duos |

### Competitive Features
| Feature | Description |
|---------|-------------|
| Real-time leaderboard | Always visible, updates live |
| Sigma Duel | Challenge friend to 60-second click battle |
| Rank display | Your rank badge shown above character in world |
| Flex emotes | Unlock emotes to taunt friends at lower ranks |

---

## Map Progression

The map visually evolves as global/personal sigma milestones are hit. This makes progress feel real and visible.

| Sigma Milestone | Map Change |
|----------------|-----------|
| 0 | Grey NPC town, basic baseplate |
| 2,000 | Gym building appears |
| 10,000 | Wolf forest area unlocks to the side |
| 50,000 | Sigma HQ skyscraper rises in center |
| 150,000 | Ohio portal glows and opens |
| 500,000 | Rizz Palace spawns, gold accents appear |
| 1,000,000 | Everything turns gold, fireworks loop |
| Prestige 1 | Prestige star appears on map |

**Design Note:** Map changes should be dramatic and noticeable. Use tweening to animate buildings rising. Players should think "wait what just happened" and explore.

---

## Daily Engagement Systems

### Login Streak Rewards
| Day | Reward |
|-----|--------|
| Day 1 | 100 Sigma |
| Day 3 | 500 Sigma + Basic Egg |
| Day 7 | 250 Rizz Tokens + Rare Pet |
| Day 14 | 1000 Rizz Tokens + Epic Egg |
| Day 30 | Exclusive "Veteran" cosmetic skin |

### Daily Quests (refreshes every 24 hours)
- "Click 1,000 times today" → 500 Sigma  
- "Survive a Sigma Rush event" → 1 Rizz Token  
- "Beat your friend's score" → 2x multiplier for 1 hour  
- "Hatch an egg" → 200 Sigma  
- "Reach a new rank" → 500 Rizz Tokens  

### Weekly Challenge
- Top 3 sigma earners of the week get an exclusive cosmetic
- Creates urgency and drives competitive play
- Announced server-wide with a banner

---

## Audio Design

Sound is an underrated dopamine driver. Every audio cue should feel satisfying.

| Sound | Trigger | Notes |
|-------|---------|-------|
| Click SFX | Every click | Evolves with rank — dull thud → deep sigma boom |
| Critical hit | GIGACHAD crit | "SIGMA!" voice clip |
| Rank up jingle | New rank achieved | Memorable, satisfying fanfare |
| Event start | Random event begins | Tempo increases, unique per event |
| Egg hatch | Pet reveal | Dramatic drum roll → reveal sting |
| Prestige fanfare | Prestige triggered | Big orchestral hit, fireworks SFX |
| Background music | Always | Ohio phonk / brainrot playlist, loops |
| Combo SFX | Combo chain active | Rising pitch as combo multiplies |

---

## Folder Structure

Planned Roblox Studio / Rojo folder structure:

```
SigmaSimulator/
├── default.project.json
└── src/
    ├── server/
    │   ├── GameManager.lua         — Core game logic, events, rank system
    │   ├── DataStore.lua           — Save/load player data
    │   ├── EventManager.lua        — Random event scheduler
    │   └── PetManager.lua          — Pet income calculations
    ├── client/
    │   ├── ClickHandler.lua        — Click input + visual feedback
    │   ├── UIManager.lua           — All GUI updates
    │   ├── ComboTracker.lua        — Combo system client-side
    │   └── MapWatcher.lua          — Triggers map changes based on sigma
    └── shared/
        ├── Upgrades.lua            — Upgrade data table
        ├── Pets.lua                — Pet data table
        ├── Ranks.lua               — Rank thresholds + rewards
        └── Events.lua              — Event definitions
```

---

## Launch Roadmap

### Week 1 — Core MVP
- [ ] Baseplate map set up
- [ ] Click system working
- [ ] Sigma Points leaderboard
- [ ] 5 basic upgrades
- [ ] 4 ranks (NPC → Sigma)

### Week 2 — Content Expansion
- [ ] All 12 ranks
- [ ] Full upgrade tree
- [ ] Pet system + egg hatching
- [ ] 3 random events
- [ ] Daily login reward

### Week 3 — Social & Polish
- [ ] Co-op friend boost
- [ ] Sigma Duel
- [ ] Map progression (3 stages)
- [ ] Sound design complete
- [ ] Daily quests

### Week 4 — Endgame & Go Live
- [ ] Prestige system
- [ ] All 6 random events
- [ ] Full map progression
- [ ] DataStore saving
- [ ] Playtesting with friends
- [ ] Publish to Roblox

---

## Key Design Rules (Never Break These)

1. **Never let the player feel stuck** — always show the next goal
2. **Every 30 seconds = unlock/reward something**
3. **Co-op must feel better than solo**
4. **Map must visually evolve — progress needs to be seen**
5. **Audio feedback on every meaningful action**
6. **Prestige = celebration, not punishment**
7. **No pay-to-win — Rizz Tokens are cosmetic only**

---

*Document created: March 16, 2026*  
*Last updated: March 16, 2026*
