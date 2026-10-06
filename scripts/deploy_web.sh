#!/usr/bin/env bash
# scripts/deploy_web.sh - Chalk Web Portal Deployment & Validation Suite
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WEB_DIR="${PROJECT_ROOT}/web"

echo "=========================================================="
echo "  CHALK WEB PORTAL — DEPLOYMENT & INTEGRITY SUITE"
echo "=========================================================="

# 1. Structural Sanity Verification
echo "==> Step 1: Validating file structure..."
for required_file in "index.html" "assets/favicon.svg" "assets/logo.png"; do
    if [[ ! -f "${WEB_DIR}/${required_file}" ]]; then
        echo "❌ ERROR: Missing required asset: ${WEB_DIR}/${required_file}"
        exit 1
    fi
done
echo "    ✓ All required web files present."

# 2. Monochrome Brand Audit (Zero Purple/Indigo Enforcement)
echo "==> Step 2: Enforcing strict monochrome palette..."
if grep -i -E "purple|indigo|violet|#4f46e5|#7c3aed|#6366f1" "${WEB_DIR}/index.html" > /dev/null; then
    echo "❌ ERROR: Detected forbidden purple/indigo color classes in index.html!"
    exit 1
fi
echo "    ✓ Strict monochrome palette verified (0 forbidden color tokens)."

# 3. Mode Handling
MODE="${1:-serve}"

case "${MODE}" in
    serve|preview)
        PORT="${PORT:-8080}"
        echo "==> Starting local preview server on http://localhost:${PORT}..."
        echo "    Press Ctrl+C to terminate."
        cd "${WEB_DIR}"
        python3 -m http.server "${PORT}"
        ;;
    cloudflare)
        echo "==> Deploying to Cloudflare Pages..."
        if ! command -v wrangler &> /dev/null && ! command -v npx &> /dev/null; then
            echo "❌ ERROR: Neither wrangler nor npx is installed."
            exit 1
        fi
        npx wrangler pages deploy "${WEB_DIR}" --project-name="chalk-web"
        echo "    ✓ Successfully deployed to Cloudflare Pages."
        ;;
    gh-pages)
        echo "==> Deploying to GitHub Pages branch (gh-pages)..."
        cd "${PROJECT_ROOT}"
        git subtree push --prefix web origin gh-pages
        echo "    ✓ Successfully pushed web/ to gh-pages branch."
        ;;
    test)
        echo "    ✓ All pre-deployment tests passed successfully."
        ;;
    *)
        echo "Usage: $0 [serve|preview|cloudflare|gh-pages|test]"
        exit 1
        ;;
esac
