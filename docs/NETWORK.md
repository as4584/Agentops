# LexLab Network — Source of Truth

> Owner: Lex Santiago
> Last updated: 2026-04-01

---

## Physical Topology

```
Coax wall jack (Optimum / Altice)
  │
  ▼
┌─────────────────────────────────────────┐
│  Optimum / Altice Gateway               │
│  Type: Modem + Router combo             │
│  Wi-Fi: MyOptimum (ISP default)         │
│  Role: ISP gateway, modem, DHCP server  │
│  WAN IP: Dynamic (Optimum DHCP)         │
│  LAN subnet: 10.0.0.0/24 (typical)     │
└────────────────┬────────────────────────┘
                 │ Ethernet (Altice LAN → TP-Link WAN)
                 ▼
┌─────────────────────────────────────────┐
│  TP-Link Archer A2300 v1.0              │
│  Firmware: 2.2.1 Build 20250925        │
│  Internet: Dynamic IP (from gateway)    │
│  Wi-Fi: LexLab_5G / LexLab_2G          │
│  LAN subnet: 192.168.0.0/24            │
│  Admin: http://192.168.0.1 (tplinkwifi) │
│  Role: Custom router, home-lab gateway  │
└────────────────┬────────────────────────┘
                 │
    ┌────────────┼────────────┐
    ▼            ▼            ▼
  Laptop       Phone       Xbox (when testing)
  (WSL dev)    (iPhone)    192.168.0.133
```

---

## Wi-Fi Networks

| SSID | Band | Source | Purpose |
|------|------|--------|---------|
| `MyOptimum` | 2.4 + 5 GHz | Altice gateway | ISP default — Xbox parties work here |
| `LexLab_5G` | 5 GHz (ch 36, 80 MHz) | TP-Link Archer | Home-lab, dev, experiments |
| `LexLab_2G` | 2.4 GHz | TP-Link Archer | Fallback / IoT |

---

## TP-Link Configuration

| Setting | Value | Notes |
|---------|-------|-------|
| Internet type | Dynamic IP | Gets WAN IP from Altice gateway |
| UPnP | ON | |
| DMZ | OFF | |
| IPv6 | OFF | Disabled while testing |
| QoS | Basic / Standard | |
| WPA mode | WPA2-PSK | |
| Encryption | AES | |
| 5 GHz channel | 36 | |
| 5 GHz width | 80 MHz | |
| Smart Connect | OFF | Keep separate SSIDs |
| Malicious Content Filter | OFF | Disabled while testing |
| Intrusion Prevention | OFF | Disabled while testing |
| Infected Device Quarantine | OFF | |
| Access Control | OFF | |

---

## Device Assignments

| Device | MAC | Reserved IP | Network | Notes |
|--------|-----|-------------|---------|-------|
| Xbox | `A8:8C:3E:B3:7D:55` | `192.168.0.133` | LexLab (testing) / MyOptimum (stable) | Party/social works on MyOptimum only |
| Laptop (Windows + WSL) | — | DHCP | LexLab | Primary dev machine |
| iPhone | — | DHCP | LexLab | General use |

---

## Dev Machine (WSL)

| Property | Value |
|----------|-------|
| Windows host | Windows PC |
| WSL distro | Ubuntu 22.04.3 |
| Hostname | `lex` |
| GPU | RTX 4070 (8 GB VRAM) |
| RAM | 32 GB |
| Agentop workspace | `/root/studio/testing/Agentop` |
| Ollama | `localhost:11434` |
| Backend | `localhost:8000` |
| Frontend | `localhost:3007` |

---

## Remote Infrastructure

| Host | IP | Role | Access |
|------|-----|------|--------|
| Portfolio droplet | `104.236.100.245` | DigitalOcean, Caddy + Docker | SSH from Windows (blocked from WSL) |
| AI receptionist droplet | `174.138.67.169` | Separate project — DO NOT touch | SSH from Windows |

---

## Known Issues

### Xbox on LexLab (unresolved)
- **Symptom**: Party errors, "Can't get Teredo IP address", "Xbox network unavailable / Social and Gaming". Party breaks when another player joins.
- **Root cause (likely)**: Double NAT. Xbox sits behind TP-Link NAT *and* Altice gateway NAT. Teredo (IPv6 tunneling for Xbox Live party chat) fails when it can't establish an endpoint through two NAT layers.
- **Workarounds tried**: UPnP ON, reserved IP, various port configs.
- **Fix paths**:
  1. **Bridge mode on Altice gateway** — Turns it into a pure modem, eliminates double NAT. TP-Link becomes the only NAT/router. Call Optimum or check gateway admin for "bridge mode" / "passthrough" option.
  2. **DMZ the TP-Link** — On the Altice gateway, put the TP-Link's WAN IP in DMZ. This forwards all ports through, effectively making it single-NAT from Xbox's perspective.
  3. **Port forwarding for Xbox** — Forward Xbox Live ports (UDP 3544 for Teredo, TCP 3074, UDP 3074, UDP 88, UDP 500, UDP 3544, UDP 4500) on *both* routers to the Xbox IP. Tedious with double NAT.
  4. **Static route + UPnP** — Less reliable but occasionally works: enable UPnP on both devices and hope they negotiate correctly.

### WSL Networking (resolved)
- Had missing default route and DNS — restored. GitHub/Copilot path works.

---

## Current Practical Split

| Network | Devices | Rationale |
|---------|---------|-----------|
| **MyOptimum** | Xbox, anything that "must just work" | Single NAT, ISP-managed, Xbox parties stable |
| **LexLab** | Laptop, phone, router experiments, future home-lab | Custom control, AdGuard/dev tools planned |

---

## Future Plans

- [ ] **Bridge mode** on Altice gateway → single NAT → Xbox on LexLab
- [ ] **AdGuard Home** on TP-Link or Raspberry Pi for DNS-level ad blocking
- [ ] **Agentop network node** — register TP-Link as a managed node via `POST /network/nodes`
- [ ] **Router agent** — lightweight monitoring agent (bandwidth, DNS, connected devices) callable via SSH or TP-Link API
- [ ] **VLAN segmentation** — IoT devices on separate VLAN if TP-Link firmware supports it (check OpenWrt compatibility)
