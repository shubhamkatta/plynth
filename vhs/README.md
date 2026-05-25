# VHS demo recordings

Terminal recordings used in the main README. Source: [Charm VHS][vhs].

## Files

- `demo.tape` — the canonical "Plynth in 30 seconds" demo.
- Output lands in `docs/assets/demo.gif` (referenced from the README hero).

## Record / re-record

```bash
# One-time
brew install vhs

# Start a local Plynth
make up && make migrate && make seed

# Export the admin token (the seed script wrote it into .env)
export TOKEN=$(grep '^PLATFORM_ADMIN_TOKEN=' .env | cut -d= -f2)

# Record
vhs vhs/demo.tape

# Verify
file docs/assets/demo.gif

# Commit
git add docs/assets/demo.gif && git commit -m "docs: regenerate demo GIF"
```

## Editing tips

- `Set TypingSpeed 35ms` controls typing animation. Lower = faster.
- `Sleep <ms|s>` controls pacing between actions.
- `Hide` / `Show` toggles whether subsequent commands appear on screen
  (useful for setup steps that shouldn't be part of the demo).
- Run `vhs validate vhs/demo.tape` to catch syntax errors before
  recording.
- Total wall-clock for a typical run: ~30 seconds. GIF file size:
  ~1 MB.

[vhs]: https://github.com/charmbracelet/vhs
