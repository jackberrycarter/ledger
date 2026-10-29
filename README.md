# Ledger

A self-hosted household budget register — a checkbook-style ledger that
projects your balance forward from your recurring bills and paychecks, so you
can see the tight weeks coming before they arrive. Think YNAB4's register, if
it lived on a box in your house instead of someone else's cloud.

## Why this exists

I used to use YNAB4. It's long discontinued, and the modern replacements
are subscriptions that want your bank login on their servers. I wanted the
part I actually used — a running register with recurring items filled in
ahead of time — running on my own hardware, with my data in a plain file I
can back up.

I'm not a professional programmer. This was built by directing Claude
(Anthropic's AI) through a long series of conversations: I described what I
wanted, reviewed what came back, tested it against my own real data, and
iterated. Same story as my
[nutrient-tracker](https://github.com/jackberrycarter/nutrient-tracker).

## What it does

- A register per account with a running balance, color-tiered so low
  stretches stand out while you scroll
- **Recurring rules** (weekly / biweekly / monthly / etc.) that fill the
  register forward to a rolling one-year horizon — in bulk ("Generate"), for
  one rule ("Generate this"), or one occurrence at a time ("Add next")
- Hand-edited rows survive regeneration, and deleted occurrences stay deleted
- **Linked transfers** between your own accounts — both legs created
  together, deleted together, and kept balanced if you correct the amount
- **Bank sync** via [SimpleFIN Bridge](https://beta-bridge.simplefin.org/)
  (optional): pulls real transactions, clears what matches, adds what's
  missing (categorized from that payee's history), and leaves mismatches visible instead of papering over them
- A manual reconcile (type in the bank's balance) as a fallback
- **Envelope budget** (YNAB4-style) for one account: assign money to
  categories each month, leftovers roll over, overspending comes out of next
  month's Ready to Assign. Ready to Assign is worked out from the real
  balance, so it can't drift from the bank. "Fill from bills" pre-fills from
  your recurring rules
- Keyboard-first entry: a new transaction opens straight into Payee, Tab
  accepts the top payee/category suggestion and moves on, and a repeat payee
  fills in the category it was last given
- Payee → category auto-guessing, duplicate detection, a spending chart,
  one-step undo, payee filter, arithmetic in amount fields (`750-350`)
- A separate retirement projection page (401k-style accounts with employer
  match, plus home equity) at `/retirement.html` — stored in that browser only

## Running it

Needs Python 3. That's it — the server is stdlib only, the app is one HTML
file with vanilla JS, no build step.

```bash
python3 ledger-server.py --dir ./data --port 8787
# copy register.html (and retirement.html) into ./data first
```

Then visit `http://<host>:8787`. For a permanent install there's an example
hardened systemd unit in `contrib/ledger.service`, and `deploy-ledger.sh`
for pushing app updates with a rolling backup of the previous version.

Opened directly from disk with no server, `register.html` still works — it
falls back to saving in the browser's local storage.

### Bank sync (optional)

Get a SimpleFIN setup token, claim it for an access URL, and put that URL
alone in a file named `simplefin-access-url` in the data dir (`chmod 600`).
The server reads it there and never sends it to the browser. The first sync
on each account asks which bank account it maps to.

## Security

**There is no authentication.** Run it on your LAN or over a VPN like
Tailscale. Do not port-forward it or put it behind a public tunnel.

## Data

Everything lives in `ledger.json` in the data dir, written atomically, with
the last 30 versions kept in `snapshots/`. Back up the data dir and you've
backed up everything.

## License

MIT — see `LICENSE`.
