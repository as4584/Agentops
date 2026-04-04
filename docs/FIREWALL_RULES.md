# ER605 Firewall Rules — Access Control Configuration
# Based on network_vlan_strategy.json firewall_rules_intent

## Access Control Rules (to be applied via ER605 UI > Firewall > Access Control)

### Rule 1: Block IoT → Trusted
- **Name:** IoT-Block-Trusted
- **Interface:** LAN
- **Source IP Group:** 192.168.20.0/24 (VLAN 20 - IoT)
- **Destination IP Group:** 192.168.10.0/24 (VLAN 10 - Trusted)
- **Service:** All
- **Action:** DENY
- **Priority:** 10 (high)
- **Direction:** IoT → Trusted

### Rule 2: Block IoT → Infra
- **Name:** IoT-Block-Infra
- **Interface:** LAN
- **Source IP Group:** 192.168.20.0/24 (VLAN 20 - IoT)
- **Destination IP Group:** 192.168.40.0/24 (VLAN 40 - Infra)
- **Service:** All
- **Action:** DENY
- **Priority:** 11

### Rule 3: Block Guest → ALL LAN
- **Name:** Guest-Block-LAN
- **Interface:** LAN
- **Source IP Group:** 192.168.30.0/24 (VLAN 30 - Guest)
- **Destination IP Group:** 192.168.0.0/16 (All Private)
- **Service:** All
- **Action:** DENY
- **Priority:** 12

### Rule 4: Allow Guest → WAN (Internet)
- **Name:** Guest-Allow-Internet
- **Interface:** WAN
- **Source IP Group:** 192.168.30.0/24 (VLAN 30 - Guest)
- **Destination:** Any (WAN)
- **Service:** HTTP/HTTPS/DNS
- **Action:** ALLOW
- **Priority:** 13

### Rule 5: Block WAN → Ollama (11434)
- **Name:** Block-WAN-Ollama
- **Interface:** WAN (inbound)
- **Source:** Any (WAN)
- **Destination Port:** 11434
- **Action:** DENY
- **Priority:** 20

### Rule 6: Block WAN → k8s API (6443)
- **Name:** Block-WAN-K8s
- **Interface:** WAN (inbound)
- **Source:** Any (WAN)
- **Destination Port:** 6443
- **Action:** DENY
- **Priority:** 21

### Rule 7: Block WAN → noVNC (6080)
- **Name:** Block-WAN-noVNC
- **Interface:** WAN (inbound)
- **Source:** Any (WAN)
- **Destination Port:** 6080
- **Action:** DENY
- **Priority:** 22

### Rule 8: Allow Trusted → Infra (all)
- **Name:** Trusted-Allow-Infra
- **Interface:** LAN
- **Source IP Group:** 192.168.10.0/24 (VLAN 10)
- **Destination IP Group:** 192.168.40.0/24 (VLAN 40)
- **Service:** All
- **Action:** ALLOW
- **Priority:** 30

### Xbox Port Protection (DO NOT TOUCH)
- Ports UDP 88, 500, 3074, 3544, 4500 on VLAN 10 → WAN: ALLOW (default, no rule needed)
- These ports must NEVER be blocked, rate-limited, or rerouted

## IMPORTANT NOTE
The ER605 Access Control UI requires IP Groups to be created first.
Before applying rules, create these IP Groups in Preferences > IP Group:
- `VLAN10_Trusted`: 192.168.10.0/24
- `VLAN20_IoT`: 192.168.20.0/24
- `VLAN30_Guest`: 192.168.30.0/24
- `VLAN40_Infra`: 192.168.40.0/24

## DDNS Configuration
- Provider: Custom DDNS or NO-IP
- Domain: lexmakesit.com
- Requires GoDaddy DNS API key for A record updates
- ER605 path: Services > Dynamic DNS > Custom DDNS
