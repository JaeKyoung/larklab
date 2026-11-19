# Scheduling

## Option 1: cron

```bash
crontab -e
```

```bash
# Digest at 8:00 AM
0 8 * * * cd /path/to/larklab && /path/to/pixi run digest --days-back 999 --max-results 200 --batches 5 --cleanup >> /tmp/larklab.log 2>&1
# arXiv and bioRxiv at 11:00 AM, after arXiv's morning announcement (see Timing below)
0 11 * * * cd /path/to/larklab && /path/to/pixi run recommend arxiv biorxiv -n 999 >> /tmp/larklab.log 2>&1
# PubMed on its own: thousands of papers a day, so the run takes an hour or two
0 12 * * * cd /path/to/larklab && /path/to/pixi run recommend pubmed -t 0.6 -n 999 >> /tmp/larklab.log 2>&1
```

`-n 999` posts every paper above the threshold instead of the top 20. `-t` is short for `--threshold`, the minimum similarity. PubMed is far larger than the other two sources, so it gets a higher threshold (`-t 0.6`); raise it if too many papers come through. Keep the two `recommend` lines an hour apart: they share state files, so a run that finds the other one still going exits at once and the next run catches up.

Progress is logged to stdout, so `/tmp/larklab.log` shows each stage. Check registration with `crontab -l`.

> **macOS**: you may need to grant **Full Disk Access** to `cron` (or your terminal) in **System Settings → Privacy & Security** for the Gmail token to be readable.

> **Warning**: cron skips jobs when the machine is asleep or off and does not retry. Use launchd if you want missed jobs to run on wake.

> **Tip**: cron runs whatever branch is checked out in the project directory. Keep that checkout on a stable branch and develop in a separate `git worktree`.

> **Timing**: arXiv announces new papers around 20:00 US Eastern, which is 09:00 in Korea during US daylight time and 10:00 otherwise. `recommend` resumes from `data/crawl_progress.json`, so no paper is missed whatever the hour — but run it at 11:00 or later so that morning's announcement is already listed; a 09:00 run would only see it a day later. A digest run without `--summary` (the example above) does not use the Ollama chat model at all; only the embedding model is needed.

## Option 2: launchd (recommended for macOS)

launchd runs missed jobs when the machine wakes up.

1. Remove the cron job if present (`crontab -e`).
2. Create the plist, replacing the paths. For `recommend`, make a second copy with the label `com.larklab.recommend`, the arguments `recommend arxiv biorxiv` and `Hour` 11, and a third for PubMed with the label `com.larklab.recommend-pubmed`, the arguments `recommend pubmed` and `Hour` 12 (see the timing note above):

```bash
cat > ~/Library/LaunchAgents/com.larklab.digest.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.larklab.digest</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/pixi</string>
        <string>run</string>
        <string>digest</string>
        <string>--cleanup</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/larklab</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/larklab.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/larklab.log</string>
</dict>
</plist>
EOF
```

3. Load it and check:

```bash
launchctl load ~/Library/LaunchAgents/com.larklab.digest.plist
launchctl list | grep larklab
```

To disable:

```bash
launchctl unload ~/Library/LaunchAgents/com.larklab.digest.plist
rm ~/Library/LaunchAgents/com.larklab.digest.plist
```
