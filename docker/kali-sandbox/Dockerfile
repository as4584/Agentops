FROM kalilinux/kali-rolling

# Install core security toolset used by kali_shell tool in Agentop
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Network scanning / recon
    nmap masscan netdiscover arp-scan \
    # Web app scanning
    nikto gobuster dirb whatweb wafw00f \
    # WiFi / wireless
    aircrack-ng reaver bully \
    hcxdumptool hcxtools \
    # Password cracking
    hashcat john \
    # Auth brute-force
    hydra medusa \
    # SQL injection
    sqlmap \
    # SMB / Windows enumeration
    enum4linux smbmap smbclient \
    # DNS recon
    dnsutils dnsenum dnsrecon fierce \
    # Packet capture / analysis
    tcpdump tshark \
    # TLS / cert checks
    openssl \
    # HTTP tools
    curl wget \
    # Basic utils
    iputils-ping traceroute net-tools iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for unprivileged commands
RUN useradd -m -s /bin/bash agent
USER agent
WORKDIR /home/agent

CMD ["/bin/bash"]
