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
