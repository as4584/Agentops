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
