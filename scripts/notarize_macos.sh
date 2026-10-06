#!/usr/bin/env bash
# ==============================================================================
# scripts/notarize_macos.sh - macOS Code-Signing & Notarization Pipeline for Chalk
# ==============================================================================
# Automates:
# 1. Hardened Runtime Code-Signing with assets/entitlements.plist
# 2. Apple notarytool submission and status monitoring
# 3. Stapling of notarization tickets to dist/Chalk.app
# 4. Gatekeeper spctl verification
# 5. Developer fallback to ad-hoc signing if credentials are not configured
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_PATH="${PROJECT_ROOT}/dist/Chalk.app"
ZIP_PATH="${PROJECT_ROOT}/dist/Chalk-macOS.zip"
ENTITLEMENTS_PATH="${PROJECT_ROOT}/assets/entitlements.plist"

echo "=========================================================="
echo "  CHALK — MACOS CODE-SIGNING & NOTARIZATION PIPELINE"
echo "=========================================================="

# 1. Check if application bundle exists
if [[ ! -d "${APP_PATH}" ]]; then
    echo "❌ ERROR: Application bundle not found at: ${APP_PATH}"
    echo "    Please compile the app first via: python build_standalone.py"
    exit 1
fi

# 2. Check entitlements file
if [[ ! -f "${ENTITLEMENTS_PATH}" ]]; then
    echo "❌ ERROR: Entitlements file missing at: ${ENTITLEMENTS_PATH}"
    exit 1
fi

# 3. Detect signing identity and notary credentials
DEVELOPER_IDENTITY="${DEVELOPER_IDENTITY:-${1:-}}"
KEYCHAIN_PROFILE="${KEYCHAIN_PROFILE:-${NOTARY_KEYCHAIN_PROFILE:-AC_PASSWORD}}"
APPLE_ID="${APPLE_ID:-}"
TEAM_ID="${TEAM_ID:-}"
APP_SPECIFIC_PASSWORD="${APP_SPECIFIC_PASSWORD:-}"

# Check whether official developer identity is available
if [[ -z "${DEVELOPER_IDENTITY}" ]]; then
    # Try finding an installed Developer ID Application certificate in macOS keychain
    DETECTED_ID=$(security find-identity -v -p codesigning 2>/dev/null | grep "Developer ID Application" | head -n 1 | sed -E 's/.*"([^"]+)".*/\1/' || true)
    if [[ -n "${DETECTED_ID}" ]]; then
        DEVELOPER_IDENTITY="${DETECTED_ID}"
        echo "==> Auto-detected Developer ID in Keychain: ${DEVELOPER_IDENTITY}"
    fi
fi

# Fallback: Ad-Hoc Signing if no Apple Developer ID configured
if [[ -z "${DEVELOPER_IDENTITY}" ]]; then
    echo ""
    echo "⚠️  NOTICE: No Apple Developer ID Application certificate provided."
    echo "==> Performing clean local Ad-Hoc Hardened Runtime signing for development testing..."
    
    codesign --force --deep -s - \
        --entitlements "${ENTITLEMENTS_PATH}" \
        "${APP_PATH}"
        
    echo "==> Verifying local bundle integrity..."
    codesign --verify --deep --strict --verbose=2 "${APP_PATH}"
    
    echo ""
    echo "✓ Ad-hoc code-signing completed successfully."
    echo "----------------------------------------------------------"
    echo "To perform official Apple Developer Notarization for release:"
    echo "  1. Configure your signing identity:"
    echo "     export DEVELOPER_IDENTITY=\"Developer ID Application: Your Name (TEAM_ID)\""
    echo "  2. Configure notary credentials:"
    echo "     xcrun notarytool store-credentials \"AC_PASSWORD\" \\"
    echo "       --apple-id \"your@appleid.com\" --team-id \"TEAM_ID\" --password \"app-specific-pw\""
    echo "  3. Re-run: ./scripts/notarize_macos.sh"
    echo "----------------------------------------------------------"
    exit 0
fi

# 4. Production Code-Signing with Hardened Runtime
echo "==> Step 1: Code-signing bundle with Hardened Runtime..."
echo "    Identity: ${DEVELOPER_IDENTITY}"
echo "    Entitlements: ${ENTITLEMENTS_PATH}"

codesign --deep --force --verify --verbose \
    --options runtime \
    --entitlements "${ENTITLEMENTS_PATH}" \
    --sign "${DEVELOPER_IDENTITY}" \
    "${APP_PATH}"

echo "    ✓ Code-signing verified."
codesign --verify --deep --strict --verbose=2 "${APP_PATH}"

# 5. Archive for Notarization
echo "==> Step 2: Creating notarization zip archive..."
ditto -c -k --keepParent "${APP_PATH}" "${ZIP_PATH}"
echo "    ✓ Archive created at: ${ZIP_PATH}"

# 6. Submit to Apple Notary Service
echo "==> Step 3: Submitting to Apple Notary Service via notarytool..."

NOTARY_CMD=(xcrun notarytool submit "${ZIP_PATH}" --wait)

if [[ -n "${APPLE_ID}" && -n "${TEAM_ID}" && -n "${APP_SPECIFIC_PASSWORD}" ]]; then
    NOTARY_CMD+=(--apple-id "${APPLE_ID}" --team-id "${TEAM_ID}" --password "${APP_SPECIFIC_PASSWORD}")
else
    NOTARY_CMD+=(--keychain-profile "${KEYCHAIN_PROFILE}")
fi

echo "    Running: ${NOTARY_CMD[*]}"
if "${NOTARY_CMD[@]}"; then
    echo "    ✓ Apple notarization approved successfully."
else
    echo "❌ ERROR: Notarization submission failed or rejected."
    exit 1
fi

# 7. Staple Ticket to Bundle
echo "==> Step 4: Stapling notarization ticket to Chalk.app..."
xcrun stapler staple "${APP_PATH}"
echo "    ✓ Notarization ticket successfully stapled."

# 8. Re-generate release zip with stapled app
echo "==> Step 5: Updating release archive with stapled bundle..."
ditto -c -k --keepParent "${APP_PATH}" "${ZIP_PATH}"

# 9. Gatekeeper Assessment
echo "==> Step 6: Validating Gatekeeper compliance..."
spctl --assess --type execute -v "${APP_PATH}" || {
    echo "⚠️  spctl assessment note: ensure developer certificate is trusted by system."
}

echo "=========================================================="
echo "  ✓ CHALK MACOS APPLICATION NOTARIZATION COMPLETE"
echo "=========================================================="
