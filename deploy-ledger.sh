#!/usr/bin/env bash
# Deploy an updated app file to the ledger server. Works for either register.html (the
# ledger) or retirement.html (the projection page) - pass the destination
# filename as the second argument; defaults to register.html if omitted.
# Usage: sudo ./deploy-ledger.sh /path/to/file.html [destination-filename]
#
# Keeps a rolling backup of the previous version of THAT file, refuses to
# install anything that doesn't actually look like one of these apps (so a
# wrong file grabbed by mistake can't silently overwrite a working deploy),
# and confirms the server is actually responding afterward.

set -euo pipefail

SRC="${1:?Usage: sudo ./deploy-ledger.sh /path/to/file.html [destination-filename]}"
DESTNAME="${2:-register.html}"
DEST="/srv/ledger/$DESTNAME"
BASE="${DESTNAME%.html}"
LOG="/var/log/ledger-deploy.log"
say(){ echo "$(date '+%F %T')  $*" | tee -a "$LOG"; }

[ -f "$SRC" ] || { say "ERROR: $SRC not found"; exit 1; }

# Sanity check: refuse anything that isn't actually one of these apps, or
# that looks truncated (e.g. a copy that got cut off mid-transfer).
grep -q 'id="root"' "$SRC" || { say "ERROR: $SRC doesn't look like a ledger-family app (no #root). Aborting."; exit 1; }
grep -q '</script>' "$SRC" || { say "ERROR: $SRC has no closing </script> - looks truncated. Aborting."; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p /srv/ledger/app-backups
if [ -f "$DEST" ]; then
  cp -p "$DEST" "/srv/ledger/app-backups/$BASE-$STAMP.html"
  say "backed up the running version -> app-backups/$BASE-$STAMP.html"
fi

cp "$SRC" "$DEST"
chown ledger:ledger "$DEST"
say "deployed new $DESTNAME ($(wc -c < "$DEST") bytes, from $SRC)"

# prune old app-backups for THIS file, keep the last 20 (find, not ls -- a
# glob matching nothing makes ls exit non-zero, which set -e treats as fatal)
find /srv/ledger/app-backups -maxdepth 1 -name "$BASE-*.html" -printf '%T@ %p\n' 2>/dev/null \
  | sort -rn | awk 'NR>20{print $2}' | xargs -r rm --
say "app-backups retained for $DESTNAME: $(find /srv/ledger/app-backups -maxdepth 1 -name "$BASE-*.html" 2>/dev/null | wc -l)"

if curl -sf -o /dev/null http://127.0.0.1:8787/; then
  say "server responding OK on 8787"
else
  say "WARNING: server not responding - check: systemctl status ledger"
fi

say "done. Hard refresh the browser (Ctrl+Shift+R) to see it - a normal"
say "reload can show a cached copy of the old page."
