# TP-Link Archer A2300 (US) — Shell Access Research Log

> Target: Root shell on home router. Documented for Agentop network-node integration.
> Status: **IN PROGRESS** — firmware upload validation not yet bypassed.
> Last updated: 2026-04-02

---

## Hardware

| Field | Value |
|---|---|
| Model | TP-Link Archer A2300 (US) v1.0 |
| Firmware | 2.2.1 Build 20250925 Rel.29479 |
| CPU | Broadcom BCM4906 (ARM Cortex-A53, dual-core 64-bit) |
| RAM | 512 MB |
| Flash | NAND (UBI/UBIFS filesystem) |
| LAN MAC | `REDACTED_LAN_MAC` |
| WAN MAC | `REDACTED_WAN_MAC` |
| 2.4GHz MAC | `REDACTED_24G_MAC` |
| 5GHz MAC | `REDACTED_5G_MAC` |

**Credentials:**
- Router admin password: `REDACTED_ROUTER_PWD`
- WiFi (LexLab_2G / LexLab_5G): `REDACTED_WIFI_PWD`

**Network:**
- Router IP: `192.168.0.1`
- WAN IP: `REDACTED_WAN_IP`
- Upstream: Altice gateway in bridge mode

**Open ports:** 22 (SSH/dropbear), 53 (DNS), 80 (HTTP), 1900 (UPnP, intermittent)

---

## Web API

### Authentication
```
POST /cgi-bin/luci/;stok=/login?form=login
Content-Type: application/x-www-form-urlencoded

operation=login&password=<RSA_ENCRYPTED>
```

RSA key used for password encryption:
```
n = 00e1b73573a7b2e15e39a90b90a4b3a9baf2b58c8a1b8f88fa98e1a2fffe7b2e285d1...
e = 010001
```

After login, `localStorage.getItem('token')` returns the stok.

All API endpoints: `/cgi-bin/luci/;stok=<TOKEN>/admin/<module>?form=<name>`

### Key Working Endpoints

| Endpoint | Method | Notes |
|---|---|---|
| `/admin/firmware?form=upgrade` | GET/POST | Firmware read/upload |
| `/admin/firmware?form=config` | POST | Backup/restore (backup, restore, check, factory) |
| `/admin/firmware?form=fwup_check` | GET | Poll firmware flash progress |
| `/admin/openvpn?form=config` | GET/POST | OpenVPN config |
| `/admin/openvpn?form=openvpn_cert` | POST multipart | Generate certs |
| `/admin/pptpd?form=config` | GET/POST | PPTP VPN (enabled=off) |
| `/admin/syslog?form=mode` | GET/POST | Debug mode (currently off) |
| `/admin/system?form=reboot` | POST | Reboot |
| `/admin/system?form=sysmode` | GET | Router mode |
| `/admin/status?form=all` | GET | Full status dump |
| `/admin/cloud_account?form=check_cloud_version` | GET | Cloud firmware check |
| `/admin/wireless?form=statistics` | GET | Wireless stats |
| `/admin/print_server?form=setting` | GET | Printer (no printer attached) |
| `/admin/folder_sharing?form=auth` | GET | SMB auth (disabled) |

### Firmware Upload Format
```
POST /cgi-bin/luci/;stok=<TOKEN>/admin/firmware?form=upgrade
Content-Type: multipart/form-data

Fields:
  operation = "firmware"
  image = <binary file, name="image">
  keep = "on"
```

The upload target filename is an `<input type="file" name="image">` inside `<form id="firmware-setting">`.

---

## Backup Encryption

**Outer `.bin` format:**
```
AES-256-CBC(
  zlib_compress(
    md5("Archer A2300")[0:16] + tar_archive
  )
)
Key = 2EB38F7EC41D4B8E1422805BCD5F740BC3B95BE163E39D67579EB344427F7836
IV  = 360028C9064242F81074F4C127D299F6
```

**Inner `ori-backup-userconf.bin`:**
```
AES-256-CBC(zlib_compress(XML_config))
```

**Inner tar structure:**
```
./ori-backup-userconf.bin    — AES+zlib encrypted XML config
./ori-backup-snort-rules.bin — gzip'd tar: cve.rules, cnc.rules, snort_version
./ori-backup-auc_data.bin    — gzip'd tar: auc_tp.session (JSON)
```

---

## Backup XML UCI Config (key sections)

```xml
<!-- dropbear -->
Port=22, RootPasswordAuth=on, SysAccountLogin=off, DisableIpv6=on, PasswordAuth=on

<!-- dnsmasq -->
boguspriv=1, resolvfile=/tmp/resolv.conf.auto, authoritative=1
leasefile=/tmp/dhcp.leases  ← no dhcpscript (potential injection point, not exploited)

<!-- firewall -->
includes: /etc/firewall.user, /usr/share/miniupnpd/firewall.include,
          /etc/firewall.d/qca-nss-connmgr

<!-- ucitrack -->
network → exec /usr/local/bin/jiggle_firewall
appflow → exec /usr/local/bin/apply_appflow
dhcp    → init dnsmasq
dropbear→ init dropbear
firewall→ init firewall
```

---

## Dropbear Deep Dive

The router runs a **custom TP-Link build of dropbear** that adds `-L` flag:

```
-L              Enable SSH session login
-C              Use Web Server account login
```

**Without `-L`**, dropbear authenticates successfully but rejects ALL session types:
- Shell (`session` channel) → `Couldn't open initial channel`
- PTY allocation → blocked
- SCP/SFTP → blocked
- Port forwarding → blocked

The dropbear init script (`/etc/init.d/dropbear`) has the `-L` flag commented out:
```sh
# H) enable ssh session login
#config_get_bool val "${section}" RemoteSSH 0
#[ "${val}" -eq 1 ] && append args "-L"
```

Adding `RemoteSSH=1` to the UCI dropbear config in backups does NOT work because:
1. The code path is commented out in the init script
2. Backup restore bypasses `uci commit` so the exec hooks don't fire

**`/etc/rc.local` is executed on boot** via `/etc/init.d/done` (START=95):
```sh
[ -f /etc/rc.local ] && { sh /etc/rc.local }
```

The default rc.local just runs `tddp &`.

**Target modification:** Add to rc.local:
```sh
/usr/sbin/dropbear -L -p 2323 &
```

---

## Failed Approaches (V3–V9)

| Version | Technique | Failure Reason |
|---|---|---|
| V3 | Enable SSH via UCI backup XML | SSH port opens, auth works, dropbear blocks all sessions (missing -L) |
| V4 | `rc.local` injected into outer tar | Restore only extracts `ori-backup-*` entries, ignores others |
| V5 | `ucitrack` exec injection | Restore handler bypasses `uci commit`; exec hooks don't fire |
| V6 | Firewall include path injection | Firewall init validates paths, doesn't shell-source them |
| V7 | OpenVPN `up` script | Init script uses fixed known fields only; custom UCI options stripped |
| V8 | Path traversal in snort/auc inner tars | Extraction sanitizes `../` and absolute paths |
| V9 | Tar symlink attack in inner tars | Extraction blocks symlink creation |

**Why ALL backup approaches fail:** The snort/auc tar extraction is sandboxed — extracts to fixed hardcoded directories. No path traversal, no symlinks, no arbitrary file placement.

---

## Firmware Analysis

**Downloaded firmware:**
```
File: A2300v1-up-2.2.1_Build_20250925_Rel.29479_nosign_2025-09-25_16.12.07.bin
Size: 49,158,435 bytes (46.9 MB)
URL:  https://static.tp-link.com/upload/firmware/2025/202509/20250930/A2300v1-up-2.2.1_...zip
```

### Header Structure

```
Offset  Size  Content
------  ----  -------
0x000   4     File size (big-endian uint32) = 0x02EE1923
0x004   12    MD5 hash (see algorithm below)
0x010   N     "JKW9fw-type:Cloud\n" + null padding to 0x100
0x110   2     0x0100 (version?)
0x114   18    Board constant block 1: aa55 <board_id_1> 55aa
0x128   8     Zero padding
0x130   128   RSA signature block (for Cloud variant)
0x1B0   32    Zero padding
0x1D0   2     0x0100
0x1D4   18    Board constant block 2: aa55 <board_id_2> 55aa
0x1E8   152   Zero padding → then 0xFF fill → content starts ~0x2000
0x280   16    fw_id / content hash: D9529C90F91A36D29DC5234A2A881FF4
...
0xF56B  LZMA data (kernel/DTB)
0x5F430 Gzip data
0x36190F UBI image start
```

**Board constant blocks are identical across ALL firmware versions** — hardware-specific constants, not firmware content.

### Firmware Type Table (from nvrammanager binary)

| Type String | Product Code | Flag |
|---|---|---|
| `"Cloud"` | `JKW9` | 2 (RSA verify) |
| `"US"` | `5553` | 1 (inline MD5) |
| `"UK"` | `554B` | 1 |
| `"EU"` | `4555` | 1 |
| `"BR"` | `4252` | 1 |
| `"JP"` | `4A50` | 1 |
| `"CA"` | `4341` | 1 |

### Header MD5 Algorithm (from nvrammanager ARM disassembly)

```python
import hashlib

TPLINK_SALT = bytes.fromhex("7a2b15ed9b98596de504ab44ac2a9f4e")

def compute_firmware_md5(fw_data: bytes) -> bytes:
    """Compute TP-Link firmware header MD5: bytes 4-15."""
    # Zero out the 12-byte hash field (bytes 4-15), preserve rest
    tmp = bytearray(fw_data)
    tmp[4:16] = b'\x00' * 12
    # Overlay salt at bytes 4-19 (overwrites zeros AND bytes 16-19 of product ID)
    tmp[4:20] = TPLINK_SALT
    # MD5 of bytes 4 through end
    return hashlib.md5(bytes(tmp[4:])).digest()[:12]
```

**Verification:** `compute_firmware_md5(orig_fw) == orig_fw[4:16]` ✓

### RSA Signature (Cloud type)

The 128-byte block at 0x130 is RSA-1024 signature over `MD5(fw[20:] with sig zeroed)`.

RSA public key extracted from nvrammanager:
```
Algorithm: RSA-1024
KeyBlob:   CgIAAACkAABSU0ExAAQAAAEAAQA9pf6sroLiNY/K6P3sHjjclJ4H...
           (Microsoft PUBLICKEYBLOB base64 in data section)
```

### Firmware Section Table Structure

Embedded section table starting at offset ~0x1014 of the firmware:

```
Section: support-list
  data_offset = 44 (0x2C)
  data_size   = 538 (0x21A)
  next_offset = 582 (0x246)  → absolute from section area start

Section: soft-version
  data_offset = 626 (0x272)   → (582 + 44)
  data_size   = 141 (0x8D)
  next_offset = 767 (0x2FF)

Section: merge-config
  data_offset = 811 (0x32B)   → (767 + 44)
  data_size   = 1488 (0x5D0)
  next_offset = 0              → LAST section
```

**Support-list contents** (the router accepts this firmware if SupportList matches):
```
ID:Archer A2300(US)
HW:1.0
FW:2.2.0
SupportList:
Archer A2300(US) ver:1.0
```

**soft-version field:**
```
soft_ver:2.2.1 Build 20250925 Rel. 29479
fw_id:D9529C90F91A36D29DC5234A2A881FF4
```

`fw_id` matches the 16-byte value at header offset 0x280.

### UBI / UBIFS Layout

```
UBI image start:   0x36190F (offset in firmware file)
UBI image size:    45,613,076 bytes (43.5 MB)
PEB size:          128 KB (0x20000)
VID header offset: 0x800
Data offset:       0x1000
Total PEBs:        348
```

**UBIFS superblock parameters:**
```
min_io_size:  2048
leb_size:     126976 (0x1F000)
leb_cnt:      346
max_leb_cnt:  2048
max_bud_bytes:8388608
fmt_version:  4
default_compr:2 (zlib)
```

**Single UBI volume:**
```
vol_id:          0
vol_name:        rootfs_ubifs
reserved_pebs:   346
alignment:       1
vol_type:        dynamic
```

---

## Rootfs Layout (Extracted)

Filesystem extracted from UBIFS via `ubireader_extract_files`.

Key files modified/analyzed:

| File | Notes |
|---|---|
| `/etc/rc.local` | **Executed on every boot (START=95)**. Contains `tddp &`. Target for dropbear injection. |
| `/usr/sbin/dropbear` | Custom TP-Link build. Supports `-L` (enable sessions) and `-C` (web account login). Without `-L`, ALL session types are rejected. |
| `/etc/init.d/dropbear` | Has RemoteSSH / `-L` code path **commented out** |
| `/etc/init.d/done` | START=95, runs rc.local |
| `/lib/upgrade/platform.sh` | `platform_check_image() { return 0; }` — always passes! |
| `/usr/bin/nvrammanager` | 68KB ARM ELF, handles firmware check (-c) and upgrade (-u) |
| `/usr/lib/lua/luci/controller/admin/firmware.lua` | Web UI firmware upgrade handler (compiled Lua bytecode) |
| `/usr/bin/nc` | Symlink to busybox (netcat available) |
| `/bin/sh`, `/bin/ash` | Symlinks to busybox |

---

## nvrammanager Firmware Validation (ARM Disassembly)

`nvrammanager -c <file>` path calls `CheckUpgradeFile(0x17590)`:

1. Open and mmap the file
2. Call inner check `0x17af0`
3. If inner check returns 0 → print "check ok", return 0 (SUCCESS)

Inner check `0x17af0`:
1. Size bounds check → fail if `(size - 0x1814) > 0x3700000`
2. Read fw-type string from header
3. Look up fw-type in type table:
   - Type `"Cloud"` → FLAG=2, call RSA verify function
   - Type `"US"/"EU"/etc` → FLAG=1, call inline salt-based MD5 check
   - Type NOT FOUND → skip both checks, fall through to section check
4. **FLAG=1 (MD5 success path):** return `0x4655` (FAIL — treated as error by caller)
5. **FLAG=2 (RSA success path):** return `0x4655` (FAIL — same)
6. **Fallthrough (MD5/RSA FAILED or type not found):** call `check_firmware(0x132a4)`
7. If `check_firmware` returns 0 → return 0 (SUCCESS)

`check_firmware(0x132a4)`:
1. Calls `0x12210` — section table parser
2. `0x12210` calls `0x12360` — section chain validator
3. `0x12360` walks the section chain, validating `data_offset + data_size == next_section_offset`
4. Returns nonzero if chain is valid (last section returns `data_offset + data_size`)
5. Via CLZ trick: if 0x12360 returns nonzero → `check_firmware` returns 0 (SUCCESS)

**Critical insight — the type table lookup:** When fw-type is `"Cloud"`:
- RSA verification is attempted against the 128-byte signature block
- If RSA PASSES → return 0x4655 (ERROR for the caller) — counterintuitive!
- If RSA FAILS → fall through to `check_firmware` (section chain check)
- If section chain passes → return 0 (SUCCESS)

**This means:** modifying firmware content INVALIDATES the RSA signature, which causes the RSA verify to FAIL, which causes it to fall through to `check_firmware`, which only checks the section table structure (which we don't modify). Therefore: **a firmware with modified UBI content but intact section table should pass nvrammanager -c!**

### Why "Unable to upgrade" Still Occurs

The web UI flow is:
1. Upload firmware → saved to `/tmp/firmware.bin`
2. `upgrade_read` operation: size/MD5 check → writes to `/tmp/firmware_status.lua`
3. `fwup_check` polling: reads `/tmp/firmware_status.lua`
4. If status has `error_code` → returns `err_failed` → JS shows "Unable to upgrade."
5. If OK → calls `nvrammanager -c` → if passes → calls `nvrammanager -u` → flashes

The upload validation also includes a **file length check** and a **separate MD5 check** before calling nvrammanager. These are from the firmware.lua bytecode. The MD5 check at this stage is comparing firmware content against something (possibly the `fw_id` field).

---

## Firmware Modification Attempts

### Attempt 1 — Full UBIFS Rebuild

Rebuilt entire UBIFS with `mkfs.ubifs` from extracted+modified rootfs.

**Problem:** Even though same files, UBIFS internal structure (node positions, timestamps, journal) differs completely from original → `upload_size_check` or internal validation differed → rejected.

### Attempt 2 — In-Place Patch (rc.local data node)

Located rc.local content UBIFS data node via deflate signature scanning:

```python
# rc.local content is in a UBIFS data node at firmware offset 0x1A24707
# Node structure (48-byte header + compressed payload):
#   magic[4]=0x06101831, crc[4], sqnum[8], len[4],
#   node_type[1]=1 (DATA), ..., ino_num[8], size[4],
#   compr_type[2]=2 (zlib), data_size[2], decompr_size[4]
#   payload[N] = zlib-deflate compressed file content
```

Original content (111 bytes compressed):
```
# Put your custom commands here...
tddp &
exit 0
```

Patched content (96 bytes compressed, fits in original space):
```
# Put your custom commands here...
/usr/sbin/dropbear -L -p 2323 &
tddp &
exit 0
```

Updated: node CRC (CRC32 per UBIFS spec), `data_size` field, `decompr_size` field.

The patched firmware had **113 bytes changed** (in the UBIFS data region) + **17 bytes changed** in the Lua-side fw-type experiment.

**Status:** Also received "Unable to upgrade." — the pre-nvrammanager web validation step appears to reject before nvrammanager -c is even called.

---

## Web Upload Validation Logic

From firmware.lua bytecode strings analysis:

```
"length check success" / "length check failed"
"md5 check success" / "md5 check failed"  
"firmware check OK" / "firmware check fail"
```

The flow appears to be:
1. **Length check** — verify file size matches expected
2. **MD5 check** — verify `fw_id` in firmware header matches MD5 of content
3. **nvrammanager -c** — section table + RSA/hash structural check
4. **nvrammanager -u** — flash

The `fw_id` at 0x280 = `D9529C90F91A36D29DC5234A2A881FF4` is likely an MD5 of the UBI content or some subset thereof. Modifying the UBIFS node changes the underlying data, which changes this MD5, causing "md5 check failed" before nvrammanager is even called.

---

## Remaining Attack Surface

### High Priority
1. **Calculate correct `fw_id`** — reverse the exact range/salt used by the MD5 check in firmware.lua bytecode. If `fw_id = MD5(fw[0x36190F:])` (the UBI section), patching it into offset 0x280 AND recomputing the header MD5 at bytes 4-15 should make the upload pass all checks.

2. **Cloud firmware update hijack** — router checks for updates via `check_cloud_version` and can be triggered with `cloud_upgrade`. If DNS can be poisoned (we have LAN access), redirect `static.tp-link.com` to a local server serving our modified firmware.

3. **PPTP VPN** — currently disabled. If enabled, PPTP provides network-level access without needing shell. However PPTP is deprecated and may not help get a shell.

4. **dnsmasq `dhcpscript`** — the UCI config has no `dhcpscript` set (injectable via backup XML). If a script can be placed at a known path (e.g., via snort tar extraction), setting `dhcpscript` to that path would execute it on DHCP lease events. Need to confirm snort extraction path first.

5. **Syslog debug mode** — currently off. Enabling might expose additional attack surface.

### Lower Priority
6. Try flashing the **2021 signed firmware** (2.0.3) — it may have had telnet enabled. The router might accept downgrade.
7. Physical UART serial console — BCM routers typically have a 3.3V UART on the PCB.

---

## Tools & Scripts

All on the agent machine (WSL2):

| File | Purpose |
|---|---|
| `/tmp/rootfs/` | Full rootfs extracted from firmware UBIFS |
| `/tmp/ubi_extract/ubi_image.bin/img-0_vol-rootfs_ubifs.ubifs` | Original UBIFS image |
| `/tmp/A2300v1-up-2.2.1_*.bin` | Original firmware (49,158,435 bytes) |
| `/tmp/firmware_mod.bin` | In-place patched firmware (rc.local + dropbear -L) |
| `/tmp/reads_decrypt.py` (reconstructable) | Backup AES decrypt/encrypt tool |
| `/root/studio/testing/Agentop/backup-AC2300-SSH-V9.bin` | Latest SSH backup (symlink attack) |

**Python to compute firmware header MD5:**
```python
import hashlib

SALT = bytes.fromhex("7a2b15ed9b98596de504ab44ac2a9f4e")

def fix_header_md5(fw: bytearray) -> None:
    tmp = bytearray(fw)
    tmp[4:16] = b'\x00' * 12
    tmp[4:20] = SALT
    md5 = hashlib.md5(bytes(tmp[4:])).digest()[:12]
    fw[4:16] = md5
```

---

## Agentop Integration Plan (Post-Shell)

Once shell access is obtained:
1. Generate SSH keypair, install `~/.ssh/authorized_keys` on router
2. Confirm `dropbear -L` persists across reboots via rc.local
3. Register router in `docs/NETWORK.md` as Agentop network node
4. Create `backend/agents/router_agent.py` with tools: SSH command execution, arp table read, DHCP lease dump, traffic stats
5. Wire router health metrics into Agentop's `monitor_agent`
6. Add Discord bot commands: `!router status`, `!router clients`, `!router restart`

I have the full document from the attachment. Let me produce the systematic analysis across all five steps.

STEP 1 — Fact vs Inference Extraction
#	Claim	Type	Evidence	Confidence
1	BCM4906 dual-core ARM Cortex-A53, 512MB RAM, NAND flash	Fact	Hardware inspection / status page	99%
2	Dropbear on port 22, custom build with -L flag	Fact	SSH connection + binary help output	99%
3	Without -L, dropbear rejects ALL session types (shell, PTY, SCP, SFTP, forwarding)	Fact	Reproducible SSH connection failures	99%
4	-L code path commented out in /etc/init.d/dropbear	Fact	Extracted init script source	99%
5	/etc/rc.local executed on boot via /etc/init.d/done (START=95)	Fact	Extracted rootfs inspection of both files	95%
6	Default rc.local contains only tddp &	Fact	Extracted rootfs content	99%
7	Backup outer AES-256-CBC key/IV are correct	Fact	Successful decrypt + re-encrypt round-trip	99%
8	Inner tar contains exactly ori-backup-userconf.bin, ori-backup-snort-rules.bin, ori-backup-auc_data.bin	Fact	Decrypted + extracted backup	99%
9	Backup restore only extracts ori-backup-* entries	Fact	V4 test: injected non-ori entries ignored	95%
10	Backup restore bypasses uci commit exec hooks	Fact	V5 test: ucitrack exec hooks never fired	90%
11	Snort/auc inner tar extraction sanitizes ../ and blocks symlinks	Fact	V8 + V9 tests: path traversal and symlinks rejected	95%
12	Firmware header MD5 algo: salt overlay at bytes 4–19, MD5(bytes 4–EOF), truncate to 12 bytes	Fact	ARM disassembly of nvrammanager + verified: compute_firmware_md5(orig_fw) == orig_fw[4:16]	99%
13	Firmware type table: "Cloud"→FLAG=2 (RSA), "US"→FLAG=1 (MD5), etc.	Fact	nvrammanager disassembly, string table	95%
14	nvrammanager: FLAG=1 MD5 success → returns 0x4655 (treated as FAIL by caller)	Fact	ARM disassembly control flow	90%
15	nvrammanager: FLAG=2 RSA success → returns 0x4655 (treated as FAIL by caller)	Fact	ARM disassembly control flow	90%
16	nvrammanager: RSA/MD5 failure falls through to check_firmware (section chain validator)	Fact	ARM disassembly control flow	90%
17	check_firmware only validates section chain structure (offsets sum correctly)	Fact	ARM disassembly of 0x132a4 → 0x12210 → 0x12360	85%
18	platform_check_image() in /lib/upgrade/platform.sh always returns 0	Fact	Extracted source: { return 0; }	99%
19	fw_id at offset 0x280 = D9529C90F91A36D29DC5234A2A881FF4	Fact	Firmware binary hex read	99%
20	Section table: support-list, soft-version, merge-config with offsets/sizes	Fact	Firmware binary parsing	95%
21	UBI image starts at offset 0x36190F	Fact	Firmware binary analysis	95%
22	rc.local in UBIFS data node at firmware offset 0x1A24707	Fact	Located via deflate signature scan, decompressed matches known content	90%
23	Modified firmware (113 bytes changed in UBIFS) received "Unable to upgrade"	Fact	Upload test result	99%
24	RSA signature at 0x130 is RSA-1024 over MD5 of fw[20:] with sig zeroed	Inference	Disassembly structure suggests this, but exact input range not confirmed by test	70%
25	Modified firmware would fail RSA → fall through to section chain → pass nvrammanager -c	Inference	Logical from disassembly, but nvrammanager -c was never tested in isolation on modified firmware	75%
26	Web upload has a pre-nvrammanager length check	Inference	String "length check success/failed" found in firmware.lua bytecode	80%
27	Web upload has a pre-nvrammanager MD5/integrity check	Inference	String "md5 check success/failed" found in firmware.lua bytecode	80%
28	fw_id = MD5(UBI section) or MD5(some firmware subset)	Inference	Name "fw_id" + it's a 16-byte hex value + exists alongside content	50%
29	The rejection happens at the MD5 check stage, before nvrammanager	Inference	Only "Unable to upgrade" observed — no direct evidence of which stage failed	40%
30	firmware.lua controls the upload validation pipeline	Inference	Standard TP-Link Luci pattern + firmware.lua exists, but it's compiled bytecode	75%
31	/tmp/firmware_status.lua is the IPC mechanism between validate and poll	Inference	Inferred from web API pattern (fwup_check polls, upgrade_read writes)	65%
32	firmware.lua bytecode is Lua 5.1 and decompilable	Unknown	Not attempted — TP-Link may use custom Lua VM or obfuscated bytecode	—
33	Exact algorithm that produces fw_id	Unknown	No disassembly or source for this computation	—
34	Exact input range for the "md5 check" in firmware.lua	Unknown	Bytecode not decompiled	—
35	Whether additional checks exist beyond length + MD5 + nvrammanager	Unknown	firmware.lua logic not fully recovered	—
36	What error_code is written to firmware_status.lua on rejection	Unknown	Not captured from device during failed upload	—
37	Whether nvrammanager -c is even reached during web upload	Unknown	No process monitoring during upload attempt	—
38	Whether the router accepts firmware version downgrades	Unknown	Not tested	—
39	Whether cloud update path uses the same validation pipeline	Unknown	Different code path, not analyzed	—
40	RSA public key extracted is the correct one used for Cloud signature verification	Inference	Found in nvrammanager data section near the verify function, but not confirmed by signing a test image	70%
STEP 2 — Firmware Upload Pipeline (Stage by Stage)
Stage A: HTTP Upload Handler
Field	Value
Source	/usr/lib/lua/luci/controller/admin/firmware.lua (compiled Lua bytecode)
Endpoint	POST /cgi-bin/luci/;stok=<TOKEN>/admin/firmware?form=upgrade
Content-Type	multipart/form-data, field image = binary, field operation = "firmware", field keep = "on"
Behavior	PROVEN: upload accepted, multipart parsed. Internal dispatch logic: INFERRED from strings only.
Evidence	Successful upload (HTTP 200 with JSON) observed, followed by "Unable to upgrade" on fwup_check poll
Missing	Decompiled firmware.lua — the entire dispatch logic between receiving the file and returning status
Stage B: File Persistence
Field	Value
Source	firmware.lua (inferred)
Path	/tmp/firmware.bin (INFERRED — standard TP-Link pattern, not confirmed)
Behavior	INFERRED: upload saved to /tmp before validation
Evidence	None direct. The device has no shell to observe /tmp.
Missing	Confirmation of temp file path and whether file is fully written before validation begins
Stage C: Length Check
Field	Value
Source	firmware.lua bytecode
Behavior	INFERRED: compares uploaded file size against expected value
Evidence	Strings "length check success" / "length check failed" in bytecode. No control flow recovered.
Return condition	UNKNOWN — what "expected" means (header field? hardcoded? computed?)
Missing	(1) What the expected length is compared against. (2) Whether this check rejected the modified firmware (same size as original — it should pass if it's a size comparison).
Assessment	If the modified firmware is the same byte count as original (49,158,435), this check should PASS. But "length" could mean something other than file size.
Stage D: Integrity Check (MD5 / fw_id)
Field	Value
Source	firmware.lua bytecode
Behavior	INFERRED: computes some hash of firmware content and compares against fw_id or header MD5
Evidence	Strings "md5 check success" / "md5 check failed" in bytecode. fw_id exists at offset 0x280.
Return condition	UNKNOWN — exact hash algorithm, input range, comparison target
Missing	This is the critical gap. The exact computation is not recovered. Possibilities: (a) MD5(fw[UBI_start:]) vs fw_id, (b) MD5(fw[section_data_start:]) vs fw_id, (c) MD5(entire file with header fields zeroed) vs fw_id, (d) something else entirely.
Assessment	This is the most likely rejection point for the modified firmware. The modification changed UBIFS content, which would change any whole-content hash.
Stage E: nvrammanager -c
Field	Value
Source	/usr/bin/nvrammanager (68KB ARM ELF)
Behavior	PROVEN via disassembly: size bounds check → type table lookup → RSA or MD5 verify → on failure, fall through to section chain check → section chain valid = return 0 (SUCCESS)
Return condition	PROVEN: returns 0 on success, nonzero on failure
Key insight	For "Cloud" type firmware: RSA failure (due to content modification) causes fallthrough to section chain check. Section chain is unmodified → should return 0.
Missing	(1) Whether this stage is actually reached during web upload of modified firmware. (2) No isolated test of nvrammanager -c on the modified firmware (would require shell access).
Stage F: Flash Trigger
Field	Value
Source	nvrammanager -u (inferred from standard TP-Link pattern)
Behavior	INFERRED: writes firmware to NAND flash
Evidence	No direct evidence — never reached in testing
Missing	Everything — this stage was never reached
Pipeline Summary
Confidence that rejection occurs at Stage D: 60%. It's the strongest hypothesis but lacks direct proof.

STEP 3 — The Critical Gap
The single most critical missing link: The decompiled logic of firmware.lua
Specifically, the function that computes and compares the integrity hash between the upload handler and the nvrammanager -c call.

Why it is the bottleneck:

Every failed upload returns only "Unable to upgrade" — no differentiation between which stage failed
The fw_id computation algorithm is completely unknown — only the 16-byte output value is known
Without knowing the exact input range and algorithm, any fw_id recomputation is guesswork
nvrammanager -c behavior is well-understood but irrelevant if the pipeline never reaches it
What component holds the answer:

The file /usr/lib/lua/luci/controller/admin/firmware.lua — compiled Lua bytecode. It contains the upgrade_read operation handler that runs the length check, MD5 check, and invokes nvrammanager.

Observable artifacts that would confirm it:

Artifact	How to obtain	What it proves
Decompiled firmware.lua source	luadec / unluac on the bytecode extracted from rootfs	Exact validation algorithm, input ranges, comparison targets
/tmp/firmware_status.lua content after failed upload	Would need shell or an info leak	Which specific check failed and with what error code
Process list during upload	Would need shell	Whether nvrammanager -c is spawned at all
Serial console (UART) output during upload	Physical access to PCB UART pads	Boot log + runtime debug messages during flash attempt
The cheapest path to resolving this gap: Decompile the Lua bytecode. The file is already extracted in rootfs. Standard luadec or unluac tools can handle Lua 5.1 bytecode if TP-Link hasn't modified the Lua VM opcode table.

STEP 4 — Hypothesis Tracker
#	Hypothesis	Supporting Evidence	Contradicting Evidence	Confidence	Cheapest Validation
H1	fw_id is MD5(fw[UBI_start:]) (MD5 of UBI image region)	fw_id is 16 bytes (MD5 size); UBI is the main content payload; standard pattern for content hashes	No direct evidence of the algorithm. Could be any subset or salted.	35%	Compute MD5(fw[0x36190F:]) on original firmware and compare to D9529C90F91A36D29DC5234A2A881FF4. Single Python command.
H2	The web upload rejection occurs at the "md5 check" stage before nvrammanager	Modified firmware changes UBIFS content → any content hash changes → "md5 check failed" before nvrammanager runs	No direct observation of which stage fails. "Unable to upgrade" is opaque. Could be a different check entirely.	55%	Decompile firmware.lua to confirm control flow. Alternatively: monitor UART during upload.
H3	Fixing fw_id + header MD5 will make modified firmware pass all web checks	nvrammanager -c should pass (RSA fails → section chain check succeeds). If fw_id is the only other barrier, fixing it suffices.	Unknown: there could be additional checks in firmware.lua (e.g., UBIFS superblock hash, section content hash, signature over different range).	30%	Requires confirming H1 first. Then: recompute fw_id + header MD5 and attempt upload.
H4	Modified firmware passes nvrammanager -c	Cloud type → RSA verify fails (content changed) → falls through to check_firmware → section chain unmodified → returns 0	(a) Disassembly confidence is 85–90%, not 100%. (b) CLZ trick interpretation could be wrong. (c) Never tested.	75%	Run nvrammanager -c /tmp/firmware_mod.bin on device — requires shell. Without shell: re-verify the ARM disassembly branch conditions more carefully from the extracted binary.
H5	Cloud firmware update path (DNS hijack) bypasses web upload validation	Different code path — cloud_upgrade operation likely calls nvrammanager directly without the Lua-side MD5 check	No analysis of the cloud update code path. It may have its OWN validation. The RSA signature was specifically noted for "Cloud" type — cloud path may enforce RSA.	25%	Analyze the cloud_upgrade handler in firmware.lua or the cloud check endpoint's response format.
H6	Firmware downgrade to 2.0.3 (2021) would be accepted and may have telnet	Older TP-Link firmwares sometimes had telnet. Router may accept older versions if support-list matches.	Unknown whether version downgrade is rejected. firmware.lua may compare soft_ver against current and reject older.	20%	Attempt upload of 2.0.3 firmware (non-destructive if rejected). Check if 2.0.3 support-list matches the device.
H7	dnsmasq dhcpscript injection via backup could execute arbitrary code if a script file can be placed	UCI config allows setting dhcpscript. dnsmasq executes it on lease events.	No known method to place an arbitrary file on the filesystem. Snort/auc tar extraction is sandboxed. Backup restore only writes ori-backup-* files.	10%	First: confirm the exact extraction path for snort-rules.bin contents. If any extracted file lands at a predictable path, test dhcpscript pointing to it.
H8	The RSA public key extracted from nvrammanager is the correct verification key	Found in data section near the RSA verify function call. Microsoft PUBLICKEYBLOB format matches RSA-1024.	Not verified by test-signing. Could be a different key (e.g., for a different purpose or an older firmware version). TP-Link may have multiple keys.	65%	Use the extracted key to verify the existing signature on the unmodified firmware. If verification passes, it's the right key.
STEP 5 — Investigation Plan (Prioritized, No Exploits)
Priority 1: Decompile firmware.lua (HIGH certainty gain, ZERO device risk)
Action: Use luadec, unluac, or luajit-decompiler on the extracted /usr/lib/lua/luci/controller/admin/firmware.lua from the rootfs
Certainty gained: Resolves the critical gap — exact upload validation pipeline, fw_id algorithm, all checks
Risk: None — operates entirely on extracted files offline
Reversibility: N/A — read-only analysis
Dependencies: None — rootfs already extracted
Blocker if: TP-Link uses a modified Lua VM with shuffled opcodes. Mitigation: compare extracted Lua binary's opcode table against standard Lua 5.1
Priority 2: Compute candidate fw_id hashes offline (HIGH certainty gain, ZERO device risk)
Action: On original firmware, compute:
MD5(fw[0x36190F:]) (UBI region to EOF)
MD5(fw[0x1014:]) (section area to EOF)
MD5(fw[0x200:]) (post-header to EOF)
MD5(fw[0x280+16:]) (post-fw_id to EOF)
Any other plausible ranges
Compare each against D9529C90F91A36D29DC5234A2A881FF4
Certainty gained: If one matches, fw_id algorithm is solved. Confirms or eliminates H1.
Risk: None — offline computation
Reversibility: N/A
Dependencies: None
Priority 3: Verify RSA signature against extracted public key (MEDIUM certainty, ZERO risk)
Action: Extract the 128-byte signature at offset 0x130. Construct the expected signed payload (MD5 of fw[20:] with sig zeroed, per notes). Verify against extracted RSA-1024 public key.
Certainty gained: Confirms correct key + correct signing input. If verification passes on original firmware, H8 is confirmed and the RSA path in nvrammanager is fully understood.
Risk: None — offline
Dependencies: None
Priority 4: UART serial console connection (HIGH certainty, LOW risk)
Action: Open the router case, identify UART pads on PCB (standard for BCM4906 — typically 4-pin header: VCC, TX, RX, GND). Connect 3.3V USB-UART adapter. Monitor boot log at 115200 baud.
Certainty gained: Full boot log, runtime messages during firmware upload, possibly an interactive shell (many TP-Link devices drop to shell on UART)
Risk: Low — UART is passive monitoring. Physical case opening may void warranty (owner's prerogative). Incorrect voltage (5V instead of 3.3V) could damage the chip.
Reversibility: Case can be reassembled. UART connection is non-destructive.
Dependencies: USB-UART adapter (3.3V), soldering iron or pogo pins if no header is populated
Priority 5: Attempt old firmware upload via web UI (MEDIUM certainty, LOW risk)
Action: Download TP-Link Archer A2300 firmware v2.0.3 (2021). Attempt upload via web UI.
Certainty gained: Reveals whether version downgrade is accepted. If accepted and older firmware has telnet/shell, provides access path. Also reveals whether the web UI version-compares.
Risk: Low — if rejected, nothing happens. If accepted, device runs older (possibly less secure) firmware. Owner can re-flash current version.
Reversibility: Re-flash current firmware via web UI
Dependencies: Assumes old firmware is still downloadable from TP-Link
Priority 6: Analyze all Lua bytecode files in rootfs (MEDIUM certainty, ZERO risk)
Action: List all .lua files in extracted rootfs under /usr/lib/lua/luci/. Identify which are bytecode vs source. Decompile all bytecode. Map the full Luci controller dispatch: login → firmware → cloud_upgrade.
Certainty gained: Complete understanding of web UI validation, cloud update path, and any hidden endpoints
Risk: None — offline
Dependencies: Decompiler working (Priority 1)
Priority 7: Monitor network traffic during firmware upload (MEDIUM certainty, ZERO risk to device)
Action: During a firmware upload attempt, capture full HTTP traffic (already authenticated session). Examine the exact JSON responses from fwup_check polling — there may be more granular error codes than "Unable to upgrade" that the JS frontend discards.
Certainty gained: May reveal which specific check failed (length vs md5 vs nvrammanager)
Risk: None — passive observation
Dependencies: None, but yields less than Priority 1
I'll save this analysis to session memory.