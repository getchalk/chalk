#!/usr/bin/env bash
# scripts/deploy_web.sh - Chalk Web Portal Deployment & Validation Suite
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WEB_DIR="${PROJECT_ROOT}/web"

echo "=========================================================="
echo "  CHALK WEB PORTAL -- DEPLOYMENT & INTEGRITY SUITE"
echo "=========================================================="

# 1. Structural Sanity Verification
echo "==> Step 1: Validating file structure..."
for required_file in "index.html" "assets/favicon.svg" "assets/logo.png"; do
    if [[ ! -f "${WEB_DIR}/${required_file}" ]]; then
        echo "[ERROR] Missing required asset: ${WEB_DIR}/${required_file}"
        exit 1
    fi
done
echo "    [OK] All required web files present."

# 2. Monochrome Brand Audit (Zero Purple/Indigo Enforcement)
echo "==> Step 2: Enforcing strict monochrome palette..."
if grep -i -E "purple|indigo|violet|#4f46e5|#7c3aed|#6366f1" "${WEB_DIR}/index.html" > /dev/null; then
    echo "[ERROR] Detected forbidden purple/indigo color classes in index.html!"
    exit 1
fi
echo "    [OK] Strict monochrome palette verified (0 forbidden color tokens)."

# 3. JavaScript Syntax Verification (node --check)
echo "==> Step 3: Validating inline JavaScript syntax via node..."
python3 -c "
import re
with open('${WEB_DIR}/index.html', encoding='utf-8') as f:
    html = f.read()
scripts = re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>', html, re.DOTALL)
full_js = '\n;\n'.join(scripts)
with open('/tmp/test_web_chalk.js', 'w', encoding='utf-8') as out:
    out.write(full_js)
"
if command -v node &> /dev/null; then
    node --check /tmp/test_web_chalk.js
    rm -f /tmp/test_web_chalk.js
    echo "    [OK] Landing page JavaScript validated (0 syntax errors)."
else
    echo "    [WARN] Node.js not detected; skipped node --check."
fi

# 4. Mode Handling
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
            echo "[ERROR] Neither wrangler nor npx is installed."
            exit 1
        fi
        npx wrangler pages deploy "${WEB_DIR}" --project-name="chalk-web"
        echo "    [OK] Successfully deployed to Cloudflare Pages."
        ;;
    gh-pages|deploy|publish)
        echo "==> Deploying to GitHub Pages (https://getchalk.github.io)..."
        PAGES_REPO="${PAGES_REPO:-https://github.com/getchalk/getchalk.github.io.git}"
        DEPLOY_TMP="$(mktemp -d /tmp/chalk_pages_deploy_XXXXXX)"
        git clone --depth 1 "${PAGES_REPO}" "${DEPLOY_TMP}"
        cp -R "${WEB_DIR}/"* "${DEPLOY_TMP}/"
        touch "${DEPLOY_TMP}/.nojekyll"
        cd "${DEPLOY_TMP}"
        git add -A
        if git diff --staged --quiet; then
            echo "    [INFO] No changes detected. https://getchalk.github.io is already up-to-date."
        else
            git commit -m "deploy: update landing page, assets, and download links"
            git push origin main
            echo "    [OK] Successfully deployed web portal to https://getchalk.github.io"
        fi
        rm -rf "${DEPLOY_TMP}"
        ;;
    test)
        echo "==> Step 4: Validating i18n dictionary completeness in web/index.html..."
        python3 -c "
import re
with open('${WEB_DIR}/index.html', encoding='utf-8') as f:
    text = f.read()
langs = ['en', 'de', 'fr', 'es', 'zh']
for lang in langs:
    assert f'\"{lang}\":' in text, f'Missing language dictionary: {lang}'
print('    [OK] All 5 i18n language dictionaries verified in web/index.html.')
"
        echo "=========================================================="
        echo "    [SUCCESS] All pre-deployment tests passed cleanly."
        echo "=========================================================="
        ;;
    *)
        echo "Usage: $0 [serve|preview|cloudflare|gh-pages|test]"
        exit 1
        ;;
esac
