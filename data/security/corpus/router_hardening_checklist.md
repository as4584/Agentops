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
