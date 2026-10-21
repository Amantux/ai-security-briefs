# AI & Security Briefs

A local-only daily/weekly digest of AI security and cybersecurity news, automatically fetched from RSS/Atom feeds and pushed to GitHub.

## What this is

This pipeline:

- Fetches ~17 security and AI-lab feeds (The Hacker News, BleepingComputer, Dark Reading, Krebs on Security, Google Project Zero, Ars Technica Security, CISA advisories, OpenAI News, Google Blog, Meta Engineering, Hugging Face, and 4 Reddit subreddits)
- Normalizes items into a canonical schema with tags (AI-security, supply-chain, vulnerability, LLM, incident, policy, privacy)
- Produces a **daily brief** (top 15 items of the day) and a **weekly digest** (themes + top 10 of the week)
- Commits and pushes changes to GitHub automatically via launchd on macOS

## Why local-only

- No cloud LLM APIs — summaries are extractive and deterministic
- No API keys required — uses your existing GitHub credentials via `gh` CLI
- Runs on your Mac Studio only — no hosted compute, no recurring costs
- Byte-identical re-runs — same input produces identical output (idempotent commits)

## Prerequisites

- macOS (tested on 27.0.1)
- Python 3.9+ (`python3 --version`)
- GitHub CLI (`gh`) authenticated as `Amantux`

## One-time setup

1. Clone or create the repo:

   ```bash
   cd ~/projects
   gh repo create Amantux/ai-security-briefs --public --source=. --remote=origin --push
   ```

2. Install dependencies:

   ```bash
   cd ~/projects/ai-security-briefs
   ./run.sh --no-push
   ```

3. Install launchd agents (daily at 08:00, weekly on Mondays at 08:00):

   ```bash
   # Create launchd plists
   mkdir -p ~/Library/LaunchAgents

   cat > ~/Library/LaunchAgents/com.amantux.aibriefs-daily.plist << 'EOF'
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
     <key>Label</key>
     <string>com.amantux.aibriefs-daily</string>
     <key>ProgramArguments</key>
     <array>
       <string>/bin/bash</string>
       <string>/Users/amantux/projects/ai-security-briefs/run.sh</string>
     </array>
     <key>StartCalendarInterval</key>
     <dict>
       <key>Hour</key>
       <integer>8</integer>
       <key>Minute</key>
       <integer>0</integer>
     </dict>
     <key>StandardOutPath</key>
     <string>/Users/amantux/projects/ai-security-briefs/logs/launchd-daily.log</string>
     <key>StandardErrorPath</key>
     <string>/Users/amantux/projects/ai-security-briefs/logs/launchd-daily.log</string>
   </dict>
   </plist>
   EOF

   cat > ~/Library/LaunchAgents/com.amantux.aibriefs-weekly.plist << 'EOF'
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
     <key>Label</key>
     <string>com.amantux.aibriefs-weekly</string>
     <key>ProgramArguments</key>
     <array>
       <string>/bin/bash</string>
       <string>/Users/amantux/projects/ai-security-briefs/run.sh</string>
       <string>--weekly-only</string>
     </array>
     <key>StartCalendarInterval</key>
     <dict>
       <key>Hour</key>
       <integer>8</integer>
       <key>Minute</key>
       <integer>0</integer>
       <key>Weekday</key>
       <integer>1</integer>
     </dict>
     <key>StandardOutPath</key>
     <string>/Users/amantux/projects/ai-security-briefs/logs/launchd-weekly.log</string>
     <key>StandardErrorPath</key>
     <string>/Users/amantux/projects/ai-security-briefs/logs/launchd-weekly.log</string>
   </dict>
   </plist>
   EOF

   # Load agents
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.amantux.aibriefs-daily.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.amantux.aibriefs-weekly.plist
   ```

## Run it manually

```bash
cd ~/projects/ai-security-briefs

# Full daily run (fetch + summarize + push)
./run.sh

# Weekly-only (skip fetch, regenerate weekly digest)
./run.sh --weekly-only

# Dry run (no push to GitHub)
./run.sh --no-push
```

## Where the briefs land

- Daily briefs: `briefs/YYYY-MM-DD.md`
- Weekly digests: `weekly/YYYY-Www.md`
- GitHub: https://github.com/Amantux/ai-security-briefs

## How the weekly digest is triggered

- **Daily job (08:00 every day):** Full pipeline — fetch all sources, produce daily + weekly briefs
- **Weekly job (Monday 08:00):** Skips fetch, regenerates the completed week's digest only

Both jobs are idempotent — if no new items were produced, the git commit is a no-op.

## Adding a source

Edit `sources.json` and add your feed:

```json
{"id": "my-feed", "type": "rss", "url": "https://example.com/feed.xml", "label": "My Feed", "core_topic": true}
```

The pipeline will pick it up on the next run.

## Troubleshooting

- **Reddit 403s:** Reddit blocks `.json` endpoints from unknown UAs. The pipeline uses `.rss` Atom feeds instead (verified working 2026-10-21).
- **429 backoff:** The fetcher respects `Retry-After` headers and backs off on rate limits.
- **"git: not a repository":** Run `gh repo create Amantux/ai-security-briefs ...` once to initialize the repo.
