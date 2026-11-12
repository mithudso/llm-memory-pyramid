# Deployment reference

These are optional operator procedures. This audit did not install or start any
service. Fleet history is not a current health check. Use a project virtual
environment and explicit extraction mode; SDK credentials follow its supported
configuration, not a custom `ant auth login` adapter.

# Deployment units

## Linux (systemd user units) — the canonical consolidator

```bash
git clone https://github.com/mithudso/llm-memory-pyramid.git ~/dev/llm-memory-pyramid
python3 -m venv ~/dev/llm-memory-pyramid/.venv
~/dev/llm-memory-pyramid/.venv/bin/python -m pip install "$HOME/dev/llm-memory-pyramid[llm,ollama]"
mkdir -p ~/.config/systemd/user
cp ~/dev/llm-memory-pyramid/deploy/napmem-consolidator.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now napmem-consolidator.timer
loginctl enable-linger "$USER"     # keep user services running after logout (may need sudo)
# Configure SDK-supported credentials only if Anthropic extraction is intended.
journalctl --user -u napmem-consolidator.service -n 30   # verify
```

## macOS (launchd)

`~/Library/LaunchAgents/com.mithudso.napmem-consolidator.plist` runs
`scripts/run-naptime.sh` (bash, portable) hourly with `RunAtLoad`. See
`docs/runbooks/run-naptime-consolidator.md`.

Run exactly ONE canonical consolidator per pyramid store across the fleet —
the store is single-writer.
