#!/usr/bin/env python3
"""Store infrastructure credentials in the encrypted vault.

Usage:
    python scripts/store_infra_creds.py router
    python scripts/store_infra_creds.py wap
    python scripts/store_infra_creds.py godaddy
    python scripts/store_infra_creds.py --list
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.gateway.secrets import (
    INFRA_DEVICES,
    get_infra_credential,
    list_infra_devices,
    set_infra_credential,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Store infrastructure credentials in the vault")
    parser.add_argument("device", nargs="?", help=f"Device to store: {sorted(INFRA_DEVICES)}")
    parser.add_argument("--list", action="store_true", help="List devices with stored credentials")
    args = parser.parse_args()

    if args.list:
        stored = list_infra_devices()
        print(f"Devices with credentials: {stored or '(none)'}")
        print(f"Valid devices: {sorted(INFRA_DEVICES)}")
        return

    if not args.device:
        parser.print_help()
        return

    device = args.device.lower()
    if device not in INFRA_DEVICES:
        print(f"Error: Unknown device '{device}'. Valid: {sorted(INFRA_DEVICES)}")
        sys.exit(1)

    existing = get_infra_credential(device)
    if existing:
        overwrite = input(f"Credential for '{device}' already exists. Overwrite? [y/N]: ")
        if overwrite.lower() != "y":
            print("Aborted.")
            return

    username = input(f"Username for {device}: ").strip()
    if not username:
        print("Error: Username cannot be empty.")
        sys.exit(1)
    password = getpass.getpass(f"Password for {device}: ")
    if not password:
        print("Error: Password cannot be empty.")
        sys.exit(1)

    set_infra_credential(device, username, password)
    print(f"Credential for '{device}' encrypted and stored.")


if __name__ == "__main__":
    main()
