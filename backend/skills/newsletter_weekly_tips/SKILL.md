# Newsletter Weekly Tips — Agentop Skill

## Overview

Generates Damian's branded weekly email newsletter for Innovation Development Solutions.
Emails are captured from the "Starting a Business" sign-up page on the website.
The newsletter builds trust with leads and keeps Damian top of mind between consultations.

**Client:** Innovation Development Solutions (Damian)
**Brand:** innovationdevelopmentsolutions.com
**Model:** Ollama (local) — use `llama3` or `mistral`
**Trigger:** Weekly cron (Sunday 6pm EST) OR manual — say "generate newsletter", "write this week's email", or "newsletter for Damian"
**Output:** HTML email + plain text fallback

---

## Topic Rotation Pool

Rotate through these topics in order. Track current index in `data/newsletter_state.json`.

1. Entity formation — why structure matters from day one
2. Multistate compliance — what founders get wrong
3. Wealth management — separating personal and business finances
4. First-time founder mindset: systems over hustle
5. What investors look for in your formation documents
6. Scaling with structure: the difference between a job and a business
7. Nonprofit facilitation — the hidden advantages
8. Elite enterprise: when to move beyond the LLC
9. Building a legacy vs. building a business
10. Q&A format — answer a common founder question

After topic 10, loop back to topic 1.

---

## Brand Voice Rules

- **Tone:** Confident, practical, encouraging — never salesy or hype-y
- **Reading level:** 8th grade. No jargon without a plain-English explanation
- **Length:** 300–500 words in the body
- **Damian's identity:** Licensed financial advisor. Multi-state entity expert. Helps first-time founders AND elite enterprises. Real results. No fluff.
- **Signature phrase:** results that STICK (always capitalize STICK)
- **Never:** generic motivational filler, vague promises, excessive exclamation points

---

## Prompt Template for ContentAgent

```
You are writing a weekly email newsletter for Innovation Development Solutions,
a business consulting firm run by Damian — a licensed financial advisor and
multistate entity formation expert who works with first-time founders up to
elite enterprises.

TOPIC THIS WEEK: {topic}

Write a newsletter that follows this exact structure:
1. SUBJECT LINE: Curiosity-driven, no clickbait, under 60 characters
2. PREVIEW TEXT: One sentence teaser (under 90 characters)
3. OPENING HOOK: One sentence tied to a real founder pain point
4. MAIN INSIGHT: 2-3 paragraphs on the topic. Practical, specific, valuable.
5. QUICK WIN: One thing the reader can do TODAY (actionable, takes under 15 minutes)
6. SOFT CTA: "If you want help putting this into action, book a free consultation at innovationdevelopmentsolutions.com"
7. SIGN-OFF: "— Damian | Innovation Development Solutions"

BRAND VOICE:
- Confident and direct. Not corporate, not casual.
- Damian genuinely helps people. That comes through.
- Results that STICK (always capitalize STICK)
- Keep it under 500 words in the body.

OUTPUT FORMAT: Return JSON with these keys:
{
  "subject": "...",
  "preview_text": "...",
  "body_html": "... (full HTML email body, inline styles, mobile responsive)",
  "body_plain": "... (plain text fallback)"
}
Return only JSON. No preamble. No markdown backticks.
```

---

## HTML Email Template Spec

The `body_html` output must use this wrapper for deliverability and mobile rendering:

```html
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #ffffff;">
  <!-- Header -->
  <div style="background: #1A3C5E; padding: 24px; text-align: center;">
    <p style="color: #C8A84B; font-size: 13px; margin: 0; letter-spacing: 2px;">INNOVATION DEVELOPMENT SOLUTIONS</p>
  </div>

  <!-- Body -->
  <div style="padding: 32px 24px;">
    <!-- content goes here -->
    <!-- body text: font-size: 16px, line-height: 1.6, color: #222 -->
    <!-- headings: color: #1A3C5E -->
  </div>

  <!-- CTA Button -->
  <div style="text-align: center; padding: 16px 24px 32px;">
    <a href="https://innovationdevelopmentsolutions.com"
       style="background: #C8A84B; color: #ffffff; padding: 14px 32px; border-radius: 4px; text-decoration: none; font-weight: bold; font-size: 16px;">
      Book Your Free Consultation
    </a>
  </div>

  <!-- Footer -->
  <div style="background: #f5f5f5; padding: 16px 24px; text-align: center; font-size: 12px; color: #999;">
    <p>Innovation Development Solutions | letsmakebusinessbetter@gmail.com | 201-429-5452</p>
    <p>
      <a href="{unsubscribe_link}" style="color: #999;">Unsubscribe</a> |
      <a href="https://innovationdevelopmentsolutions.com/privacy-policy" style="color: #999;">Privacy Policy</a>
    </p>
  </div>
</div>
```

---

## Agentop Integration Flow

```
STEP 1 — GSDAgent
  Read data/newsletter_state.json → get current topic_index
  Select topic from rotation pool above

STEP 2 — ContentAgent
  Call Ollama with prompt template above
  Parse JSON response
  Store draft in data/newsletter_drafts/{date}.json

STEP 3 — Dashboard Review
  Flag draft in Agentop UI as "Pending Approval"
  Alex reviews in OrchestrationHub panel

STEP 4 — Approval
  Alex clicks "Approve" or "Request Edit"
  If edit: ContentAgent revises with feedback
  If approved: proceed to Step 5

STEP 5 — Send via Zapier MCP
  Trigger Zapier workflow: "Send Email via Mailchimp"
  Pass: subject, preview_text, body_html, body_plain
  Target: all subscribers in newsletter list

STEP 6 — Log Completion
  GSDAgent updates newsletter_state.json:
    - last_sent: {date}
    - topic_index: increment (loop at 10)
    - status: "sent"
  Log entry added to customers.db newsletter_log table
```

---

## State File

`data/newsletter_state.json`
```json
{
  "topic_index": 0,
  "last_sent": null,
  "drafts_pending": [],
  "total_sent": 0
}
```

---

## Zapier MCP Config

Add to `mcp-gateway/config.yaml` to wire up the send step:
```json
{
  "name": "newsletter-send",
  "zapier_webhook": "https://hooks.zapier.com/hooks/catch/{your-zap-id}/",
  "payload_keys": ["subject", "preview_text", "body_html", "body_plain"],
  "trigger": "newsletter_approved"
}
```

---

## Notes

- **Zero cloud cost:** All generation runs on local Ollama. Only the Zapier webhook call is external.
- **Deliverability:** Always include plain text fallback to avoid spam filters.
- **Compliance:** Footer unsubscribe link is required by CAN-SPAM law. Never remove it.
- **Brand protection:** ContentAgent must never mention competitors or make legal/financial guarantees.
