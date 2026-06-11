# Cron automation — job-radar Discovery Layer (Phase 4)

Two scheduled jobs keep the corpus fresh and surface new roles each morning:

| Script | Schedule | What it does |
|---|---|---|
| `collect_weekly.sh` | Sundays 08:00 | Incremental collect → prefilter → label → validate → score → export-index |
| `digest_daily.sh` | Weekdays 07:30 | Digest of roles scored since the last run (`--min-fit 6 --export`) |

Both run the pipeline inside the Docker service (`docker compose run --rm
job-radar …`), so the host only needs Docker + cron. Collection is **incremental
by default** (per-source cursors in `corpus/.last_collected_{source}`); the digest
tracks its own cursor in `corpus/.digest_last_run`. Both cursors are gitignored.

Each `collect_weekly.sh` stage runs **bare** on UTC-day-keyed defaults (so don't schedule
it near 00:00 UTC — the date-keyed stages would split across two stamps). `label` **spends
Batch-API budget** on the day's new survivors (already-labelled/scored jobs are excluded by
prefilter). `dedupe` is **not** a stage (prefilter does the dedup; `cli/dedupe.py` is a stub).

> `PROJECT_DIR` is auto-derived from each script's own location, so the scripts work wherever
> the repo is cloned (server: `/opt/apps/job-radar`; dev: `~/dev/job-radar`) — **no edit
> needed**. Only the **crontab lines** below need your real absolute clone path. If
> `/var/log/job-radar` isn't writable, set `JR_LOG_DIR` to a dir you own.

---

## Install (Ubuntu Server)

1. Make the scripts executable (once, after clone — use your real clone path, e.g.
   `/opt/apps/job-radar` on the server):

   ```bash
   chmod +x /opt/apps/job-radar/cron/*.sh
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
   # job-radar — weekly collection (Sundays 08:00) — use your real clone path
   0 8 * * 0 /opt/apps/job-radar/cron/collect_weekly.sh

   # job-radar — daily digest (weekdays 07:30)
   30 7 * * 1-5 /opt/apps/job-radar/cron/digest_daily.sh
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
