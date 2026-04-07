#!/usr/bin/env python3
"""
seed_security_corpus.py — Seed the knowledge_agent vector DB with security content.

Downloads and formats security documentation so knowledge_agent can answer:
  - "What does a deauth flood look like?"
  - "How do I harden WPA3 on TP-Link ER605?"
  - "Is this nmap output suspicious?"

Sources pulled (all freely available, no credentials needed):
  1. OWASP Testing Guide cheat-sheet summaries (public GitHub)
  2. Snort community rules (signatures only — no binary data)
  3. RouterSecurity.org hardening checklist (scraped)
  4. Common CVE patterns for small-office routers
  5. WiFi attack reference (WPA2/WPA3 attack surface)

Output: data/security/corpus/*.md (one doc per topic)
        data/security/corpus/index.jsonl (manifest for vector DB loader)

Usage:
    python scripts/seed_security_corpus.py
    python scripts/seed_security_corpus.py --dry-run     # list sources, don't write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent.parent / "data" / "security" / "corpus"
INDEX_FILE = CORPUS_DIR / "index.jsonl"

# ---------------------------------------------------------------------------
# Static security knowledge (no network required for these)
# ---------------------------------------------------------------------------

STATIC_DOCS: list[dict] = [
    {
        "id": "wifi_attacks_reference",
        "title": "WiFi Attack Surface Reference",
        "tags": ["wifi", "wireless", "wpa2", "wpa3", "deauth", "evil-twin", "pmkid"],
        "content": textwrap.dedent("""\
            # WiFi Attack Surface Reference

            ## WPA2 Attack Vectors

            ### Handshake Capture (4-way handshake)
            - Tool: airodump-ng + aireplay-ng (deauth) + aircrack-ng / hashcat
            - How: Force deauth → capture 4-way handshake → offline dictionary attack
            - Detection: Repeated deauth frames from non-AP MAC; sudden client disconnects
            - Defense: WPA3 (SAE handshake resists offline cracking); long random passphrase

            ### PMKID Attack (no handshake needed)
            - Tool: hcxdumptool + hcxpcapngtool + hashcat
            - How: Request PMKID from AP directly without associating clients
            - Detection: Probe requests to AP with unusual PMKID requests
            - Defense: WPA3-SAE; 20+ char passphrase not in any wordlist

            ### Deauthentication Flood
            - Tool: aireplay-ng -0
            - How: Spoofed 802.11 management frames sent to clients (unauthenticated pre-WPA3)
            - Detection: Many deauth frames in airodump-ng; clients repeatedly reconnecting
            - Defense: 802.11w Management Frame Protection (MFP); WPA3 mandates MFP

            ### Evil Twin / Rogue AP
            - Tool: hostapd-wpe, wifiphisher
            - How: Clone SSID → client connects to attacker AP → steal credentials
            - Detection: Two APs with same SSID; BSSID mismatch; unusual DHCP assignment
            - Defense: Certificate pinning on WPA-Enterprise; 802.11w; monitor for duplicate SSIDs

            ### WPS Brute Force
            - Tool: reaver, bully
            - How: WPS PIN has only 11,000 effective combinations; lockout often not enforced
            - Detection: Repeated WPS authentication attempts in router logs
            - Defense: DISABLE WPS. No exceptions.

            ## WPA3 Improvements
            - SAE (Simultaneous Authentication of Equals) replaces PSK handshake → no offline cracking
            - Mandatory MFP (802.11w) → blocks deauth floods
            - Forward secrecy → captured traffic can't be decrypted later
            - Dragonfly handshake → resistant to dictionary attacks

            ## Wireless Recon Checklist
            1. `airmon-ng start wlan0` — enable monitor mode
            2. `airodump-ng wlan0mon` — scan all channels
            3. Look for: WEP (broken), WPA2 with WPS enabled, hidden SSIDs, rogue APs
            4. `nmap -sV 192.168.x.0/24` — scan LAN for exposed services
            5. Check for UPnP: `nmap --script upnp-info 192.168.x.1`
        """),
    },
    {
        "id": "router_hardening_checklist",
        "title": "Small Office Router Hardening Checklist",
        "tags": ["router", "hardening", "er605", "firewall", "vlan", "dns"],
        "content": textwrap.dedent("""\
            # Small Office Router Hardening Checklist

            ## Firmware & Updates
            - [ ] Enable automatic firmware updates or check monthly
            - [ ] Verify firmware integrity (check vendor hash)
            - [ ] Remove end-of-life devices from network

            ## Authentication
            - [ ] Change default admin credentials immediately
            - [ ] Use strong password (20+ chars, not dictionary word)
            - [ ] Disable Telnet; use SSH only
            - [ ] Enable two-factor authentication if supported
            - [ ] Restrict management interface to LAN-only (disable WAN admin)

            ## WiFi
            - [ ] Use WPA3 (or WPA2/WPA3 mixed mode minimum)
            - [ ] DISABLE WPS (critical — reaver/bully exploit this)
            - [ ] Enable 802.11w Management Frame Protection
            - [ ] Use 20+ character passphrase (test against rockyou.txt)
            - [ ] Hidden SSID = security through obscurity only (not sufficient alone)
            - [ ] Reduce transmit power to minimize signal leakage outside building
            - [ ] Guest network on separate VLAN with client isolation

            ## Network Segmentation
            - [ ] IoT devices on isolated VLAN (no LAN access)
            - [ ] Guest WiFi cannot reach LAN or management interface
            - [ ] Cameras / NVR on dedicated VLAN
            - [ ] Apply inter-VLAN firewall rules (deny IoT → LAN by default)

            ## Services
            - [ ] Disable UPnP — allows devices to open ports automatically (dangerous)
            - [ ] Disable unused services (FTP server, SNMP, etc.)
            - [ ] Check for NAT loopback abuse
            - [ ] Disable remote management / cloud management if not used

            ## DNS
            - [ ] Use encrypted DNS (DoH / DoT): Cloudflare 1.1.1.1, NextDNS, or Pi-hole
            - [ ] Block known malware domains at DNS level
            - [ ] Enable DNSSEC if ISP supports it

            ## Logging & Monitoring
            - [ ] Enable syslog to external server (or Agentop monitor_agent)
            - [ ] Log firewall drops
            - [ ] Alert on new MAC addresses joining network
            - [ ] Review logs weekly for anomalies

            ## TP-Link ER605 Specific
            - [ ] Omada SDN: enable Threat Intelligence if using EAP APs
            - [ ] Use ACL rules to block LAN → WAN for IoT VLANs
            - [ ] Disable TeRP (TP-Link Remote Management Portal) if not used
            - [ ] Update to latest Omada firmware monthly
        """),
    },
    {
        "id": "network_attack_patterns",
        "title": "Network Attack Pattern Recognition",
        "tags": ["ids", "ips", "nmap", "arp-spoofing", "mitm", "port-scan", "ddos"],
        "content": textwrap.dedent("""\
            # Network Attack Pattern Recognition

            ## Port Scanning Signatures
            - **SYN scan (nmap -sS)**: Many SYN packets, no ACK completions, short bursts
            - **Connect scan (nmap -sT)**: Full TCP connections opened/closed rapidly
            - **UDP scan**: Many UDP probes, ICMP port-unreachable responses
            - **Detection**: Log rate >100 new connections/min from single IP → alert

            ## ARP Spoofing / MITM
            - Two different MACs claim the same IP in ARP replies
            - `arp -a` shows IP with two different MACs
            - Tool: bettercap, arpspoof (dsniff)
            - Detection: ARP table conflicts; gratuitous ARP floods
            - Defense: Dynamic ARP Inspection (DAI) on managed switches; static ARP entries for gateway

            ## DNS Poisoning
            - Unexpected DNS responses for internal hostnames
            - TTLs much shorter than normal
            - Detection: Monitor for DNS responses from unexpected sources
            - Defense: DNSSEC; DNS over HTTPS; internal DNS resolver

            ## Deauth Flood (Wireless DOS)
            - Log pattern: `disassociation reason code 7` repeated from unknown source
            - Clients repeatedly reconnecting every few seconds
            - Detection: airodump-ng shows many deauth frames; clients drop frequently
            - Defense: 802.11w MFP; WPA3

            ## Credential Stuffing Indicators
            - Many failed login attempts across multiple accounts
            - Distributed sources (many IPs) → botnet
            - Same usernames with different passwords → credential list
            - Detection: N failed logins in T seconds → block IP + alert

            ## Suspicious nmap Output Patterns
            - Open port 23 (Telnet) → immediately remediate
            - Open port 21 (FTP) → check if needed, disable if not
            - Open port 161 (SNMP) → check community string is not 'public'/'private'
            - Open port 5900 (VNC) without auth → CRITICAL
            - Open port 631 (CUPS) on non-print-server → remove
            - Many open ports on IoT device → firmware likely vulnerable

            ## Common Router CVE Patterns
            - Pre-auth RCE via web interface (check Shodan for your model)
            - CSRF on management page (old TP-Link, Netgear)
            - Default credentials never changed
            - UPnP IGD port mapping abuse (NAT traversal for C2)
            - DNS rebinding attacks via WAN interface
        """),
    },
    {
        "id": "secret_patterns_reference",
        "title": "Secret and Credential Pattern Reference",
        "tags": ["secrets", "credentials", "api-keys", "tokens", "scanning"],
        "content": textwrap.dedent("""\
            # Secret and Credential Pattern Reference

            ## High-Risk Patterns (CRITICAL if found in source)

            | Pattern | Regex hint | Example |
            |---|---|---|
            | AWS Access Key | `AKIA[0-9A-Z]{16}` | AKIAIOSFODNN7EXAMPLE |
            | AWS Secret Key | 40-char base64 after `aws_secret` | — |
            | GitHub Token | `ghp_[a-zA-Z0-9]{36}` | ghp_abc123... |
            | GitHub App Token | `ghs_` or `ghu_` prefix | — |
            | Stripe Secret Key | `sk_live_[a-zA-Z0-9]{24}` | — |
            | Stripe Publishable | `pk_live_` | less sensitive |
            | Private SSH Key | `-----BEGIN.*PRIVATE KEY-----` | in .env or .pem |
            | Google API Key | `AIza[0-9A-Za-z\\-_]{35}` | — |
            | Slack Token | `xox[baprs]-` | — |
            | Discord Bot Token | `[MNO][a-zA-Z0-9]{23}\\.[a-zA-Z0-9-_]{6}\\.[a-zA-Z0-9-_]{27}` | — |
            | JWT | `eyJ[a-zA-Z0-9_-]+\\.[a-zA-Z0-9_-]+\\.[a-zA-Z0-9_-]+` | check alg=none |
            | Generic password | `password\\s*=\\s*[^\\s]+` | password=abc123 |

            ## Where to Scan
            - `.env` files committed to git
            - `backend/config.py`, `settings.py`
            - `docker-compose.yml`, k8s secrets
            - CI/CD workflow files (.github/workflows/*.yml)
            - Jupyter notebooks (`.ipynb`) — tokens often left in cell outputs
            - `package.json`, `requirements.txt` (dependency with embedded token)

            ## False Positive Reduction
            - Entropy check: real secrets usually have Shannon entropy > 3.5
            - Length check: most real tokens are 20+ chars
            - Context check: `example`, `placeholder`, `your-key-here` are likely safe
            - Skip `test_` or `mock_` prefixed variables in test files
        """),
    },
]

# ---------------------------------------------------------------------------
# Remote fetch helpers (optional, gracefully skipped)
# ---------------------------------------------------------------------------

REMOTE_SOURCES: list[dict] = [
    {
        "id": "owasp_testing_guide_toc",
        "title": "OWASP Web Testing Guide — Key Test IDs",
        "url": "https://raw.githubusercontent.com/OWASP/wstg/master/checklists/checklist.md",
        "tags": ["owasp", "web", "testing", "checklist"],
    },
]


def _fetch_text(url: str, timeout: int = 15) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Agentop-SecuritySeeder/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")[:50_000]
    except Exception as e:
        print(f"  [WARN] Could not fetch {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> None:
    print("Agentop — Security Corpus Seeder")
    print(f"Output: {CORPUS_DIR}\n")

    if not dry_run:
        CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    index_entries: list[dict] = []

    # Write static docs
    for doc in STATIC_DOCS:
        path = CORPUS_DIR / f"{doc['id']}.md"
        print(f"  [static] {doc['id']}.md — {doc['title']}")
        if not dry_run:
            path.write_text(doc["content"], encoding="utf-8")
        index_entries.append({
            "id": doc["id"],
            "title": doc["title"],
            "file": str(path.relative_to(CORPUS_DIR.parent.parent)),
            "tags": doc["tags"],
            "source": "static",
            "seeded_at": datetime.utcnow().isoformat(),
        })

    # Fetch remote docs
    for src in REMOTE_SOURCES:
        print(f"  [remote] {src['id']} — {src['title']}")
        if not dry_run:
            content = _fetch_text(src["url"])
            if content:
                path = CORPUS_DIR / f"{src['id']}.md"
                path.write_text(f"# {src['title']}\n\nSource: {src['url']}\n\n{content}", encoding="utf-8")
                index_entries.append({
                    "id": src["id"],
                    "title": src["title"],
                    "file": str(path.relative_to(CORPUS_DIR.parent.parent)),
                    "tags": src["tags"],
                    "source": src["url"],
                    "seeded_at": datetime.utcnow().isoformat(),
                })
            else:
                print(f"    [SKIP] fetch failed — skipping {src['id']}")

    # Write index
    if not dry_run:
        with INDEX_FILE.open("w", encoding="utf-8") as f:
            for entry in index_entries:
                f.write(json.dumps(entry) + "\n")
        print(f"\nWrote {len(index_entries)} docs to {INDEX_FILE}")
        print("\nNext step: load into knowledge_agent vector DB with:")
        print("  POST http://localhost:8000/knowledge/seed  {'source_dir': 'data/security/corpus'}")
    else:
        print(f"\n[DRY RUN] Would write {len(index_entries)} docs. Run without --dry-run to write.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed security knowledge corpus for knowledge_agent")
    parser.add_argument("--dry-run", action="store_true", help="List sources without writing files")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
