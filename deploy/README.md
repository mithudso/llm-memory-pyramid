# Deployment units

## Linux (systemd user units) — the canonical consolidator

```bash
git clone https://github.com/mithudso/llm-memory-pyramid.git ~/dev/llm-memory-pyramid
pip3 install --user --break-system-packages anthropic
mkdir -p ~/.config/systemd/user
cp ~/dev/llm-memory-pyramid/deploy/napmem-consolidator.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now napmem-consolidator.timer
loginctl enable-linger "$USER"     # keep user services running after logout (may need sudo)
ant auth login --no-browser        # activate LLM extraction (else heuristic)
journalctl --user -u napmem-consolidator.service -n 30   # verify
```

## macOS (launchd)

`~/Library/LaunchAgents/com.mithudso.napmem-consolidator.plist` runs
`scripts/run-naptime.sh` (bash, portable) hourly with `RunAtLoad`. See
`docs/runbooks/run-naptime-consolidator.md`.

Run exactly ONE canonical consolidator per pyramid store across the fleet —
the store is single-writer.
