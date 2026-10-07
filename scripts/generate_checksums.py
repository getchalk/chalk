#!/usr/bin/env python3
"""
scripts/generate_checksums.py - Generate Cryptographic SHA-256 Checksums for Chalk Release Artifacts.
Standard GNU coreutils format: <hash>  <filename>
"""

import os
import sys
import hashlib
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
CHECKSUM_FILE = os.path.join(DIST_DIR, "SHA256SUMS.txt")


def compute_sha256(filepath: str) -> str:
    """Computes SHA-256 hex digest for a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def ensure_macos_zip():
    """Zips Chalk.app into Chalk-macOS.zip if Chalk.app exists and zip is missing or outdated."""
    app_path = os.path.join(DIST_DIR, "Chalk.app")
    zip_path = os.path.join(DIST_DIR, "Chalk-macOS.zip")
    
    if os.path.exists(app_path):
        print(f"Creating/updating release archive: {zip_path} from {app_path}...")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(app_path):
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, DIST_DIR)
                    zipf.write(full_path, rel_path)
        print(f"[OK] Created {zip_path} ({os.path.getsize(zip_path) / (1024*1024):.2f} MB)")


def generate_checksums():
    if not os.path.exists(DIST_DIR):
        print(f"Error: Dist directory {DIST_DIR} does not exist.")
        sys.exit(1)

    # Ensure macOS zip bundle exists if Chalk.app is present
    ensure_macos_zip()

    artifacts = []
    for item in sorted(os.listdir(DIST_DIR)):
        if item in ("SHA256SUMS.txt", ".DS_Store"):
            continue
        item_path = os.path.join(DIST_DIR, item)
        if os.path.isfile(item_path):
            artifacts.append(item)

    if not artifacts:
        print("No file artifacts found in dist/ to hash.")
        return

    checksum_lines = []
    print("\n========================================================")
    print("  CHALK DISTRIBUTION RELEASE CHECKSUMS (SHA-256)")
    print("========================================================")

    for artifact in artifacts:
        file_path = os.path.join(DIST_DIR, artifact)
        digest = compute_sha256(file_path)
        line = f"{digest}  {artifact}"
        checksum_lines.append(line)
        print(f"  {artifact:25} : {digest}")

    with open(CHECKSUM_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(checksum_lines) + "\n")

    print("========================================================")
    print(f"[OK] Checksums successfully written to: {CHECKSUM_FILE}\n")


if __name__ == "__main__":
    generate_checksums()
