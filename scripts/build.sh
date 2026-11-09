#!/usr/bin/env bash
#
# Build the add-on and repository zips, refresh pages/addons.xml and md5.
#
#   ./scripts/build.sh            # use versions from addon.xml files
#   ./scripts/build.sh 1.0.1      # bump plugin version first
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_ID="plugin.video.kinakipa"
REPO_ID="repository.kinakipa"
PAGES="$ROOT/pages"

cd "$ROOT"

version_of() {
    python3 - "$1" <<'PY'
import re
import sys
text = open(sys.argv[1], encoding='utf-8').read()
print(re.search(r'<addon[^>]*\bversion="([^"]+)"', text).group(1))
PY
}

PLUGIN_VERSION="$(version_of "$PLUGIN_ID/addon.xml")"
REPO_VERSION="$(version_of "$REPO_ID/addon.xml")"

if [[ $# -ge 1 ]]; then
    PLUGIN_VERSION="$1"
    sed -i -E "s/(<addon[^>]*\bversion=\")[^\"]+/\1${PLUGIN_VERSION}/" "$PLUGIN_ID/addon.xml"
fi

echo "Building $PLUGIN_ID $PLUGIN_VERSION"
echo "Building $REPO_ID $REPO_VERSION"

rm -rf "$ROOT/build"
mkdir -p "$ROOT/build" "$PAGES/$PLUGIN_ID" "$PAGES/$REPO_ID"

package() {
    local id="$1" version="$2"
    rm -f "$PAGES/$id/$id-"*.zip
    zip -qr "$ROOT/build/$id-$version.zip" "$id" \
        -x "$id/*/__pycache__/*" "$id/__pycache__/*" "*.pyc" "*.pyo" "*.DS_Store"
    cp "$ROOT/build/$id-$version.zip" "$PAGES/$id/$id-$version.zip"
    echo "  -> pages/$id/$id-$version.zip"
}

package "$PLUGIN_ID" "$PLUGIN_VERSION"
package "$REPO_ID" "$REPO_VERSION"

{
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo '<addons>'
    tail -n +2 "$PLUGIN_ID/addon.xml"
    tail -n +2 "$REPO_ID/addon.xml"
    echo '</addons>'
} > "$PAGES/addons.xml"

md5sum "$PAGES/addons.xml" | cut -d' ' -f1 > "$PAGES/addons.xml.md5"

cp "$PLUGIN_ID/icon.png" "$PLUGIN_ID/fanart.jpg" "$PAGES/"

echo "Done:"
echo "  addons.xml      $(wc -c < "$PAGES/addons.xml") bytes"
echo "  addons.xml.md5  $(cat "$PAGES/addons.xml.md5")"
