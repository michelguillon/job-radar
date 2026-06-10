# Cron automation — job-radar Discovery Layer (Phase 4)

Two scheduled jobs keep the corpus fresh and surface new roles each morning:

| Script | Schedule | What it does |
|---|---|---|
| `collect_weekly.sh` | Sundays 08:00 | Incremental collect → dedupe → prefilter → label → validate → score → export-index |
| `digest_daily.sh` | Weekdays 07:30 | Digest of roles scored since the last run (`--min-fit 6 --export`) |

Both run the pipeline inside the Docker service (`docker compose run --rm
job-radar …`), so the host only needs Docker + cron. Collection is **incremental
by default** (per-source cursors in `corpus/.last_collected_{source}`); the digest
tracks its own cursor in `corpus/.digest_last_run`. Both cursors are gitignored.

> Paths assume the repo lives at `/home/michel/dev/job-radar` (the M720q home
> server). Edit `PROJECT_DIR` in each script if you clone elsewhere.

---

## Install (Ubuntu Server)

1. Make the scripts executable (once, after clone):

   ```bash
   chmod +x /home/michel/dev/job-radar/cron/*.sh
   ```

2. Ensure the log directory is writable by the cron user (the scripts create it
   with `mkdir -p`, but `/var/log` needs root or a pre-created, chowned dir):

   ```bash
   sudo mkdir -p /var/log/job-radar
   sudo chown "$USER" /var/log/job-radar
   ```

3. Edit the crontab for the user that owns the Docker socket access:

   ```bash
   crontab -e
   ```

   Add:

   ```cron
   # job-radar — weekly collection (Sundays 08:00)
   0 8 * * 0 /home/michel/dev/job-radar/cron/collect_weekly.sh

   # job-radar — daily digest (weekdays 07:30)
   30 7 * * 1-5 /home/michel/dev/job-radar/cron/digest_daily.sh
   ```

   `cron` runs with a minimal environment. If `docker` is not on cron's `PATH`,
   add `PATH=/usr/local/bin:/usr/bin:/bin` at the top of the crontab.

---

## Verify they're installed

```bash
crontab -l                 # list scheduled jobs
systemctl status cron      # confirm the cron daemon is running
```

## Check the logs

Each run timestamps every line (UTC) and appends to a per-job log:

```bash
tail -f /var/log/job-radar/collect_weekly.log
tail -f /var/log/job-radar/digest_daily.log
```

The latest digest table is also written to `corpus/digest_{YYYYMMDD}.md`.

## Run manually (testing)

The scripts are plain wrappers — run them directly to test end-to-end:

```bash
/home/michel/dev/job-radar/cron/digest_daily.sh
/home/michel/dev/job-radar/cron/collect_weekly.sh
```

Or run a single stage without touching the cursor / log:

```bash
docker compose run --rm job-radar python -m cli.digest --since yesterday   # no cursor advance
docker compose run --rm job-radar python -m cli.collect --source all --dry-run
```
