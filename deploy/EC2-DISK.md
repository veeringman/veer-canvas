# EC2 disk — backlog (14 GB root)

Host: VeerSetu `ubuntu@3.216.30.113`. Surveyed 2026-08-21 at **87% full**; Rust `target/` cleanup brought it to ~74%.

## Done

| Item | Notes |
|------|--------|
| Wipe Cargo `target/` | AuthBuddy + both `veer-ai` trees. AuthBuddy binary moved to `/usr/local/bin/authbuddy`. |
| No Rust **builds** on EC2 | `site-deploy.sh` must not rustup/cargo. Ship `services/veer-ai/dist/veer-ai` or keep `data/bin/veer-ai`. |
| Shared Drive venv | `/var/lib/veercanvas/drive-venv`; site `data/drive-venv` is a symlink. |
| Latest APK only | `~/AuthBuddy/.../releases/BuddyAuthenticator-latest.apk`. Older APKs stay on Drive. |
| Snap disabled revisions, apt cache, journal vacuum | One-shot reclaim 2026-08-21. |
| On-box backup retention **3 days** | `BACKUP_RETAIN_DAYS=3` (Drive dated tarballs still 14d). |

## Still to do

1. **Grow EBS 14 GB → ~30 GB** — durable fix; five sites + Docker Postgres + backups do not fit comfortably.
2. **Remove rustup + Cargo registry** (`~/.rustup` ~600 MB, `~/.cargo` ~480 MB) once no on-box compile path remains (same change as “no Rust on EC2”).
3. **Syslog flood** — `/var/log/syslog` was ~110 MB and growing. Find the noisy unit and tighten logrotate.
4. **Stop copying a full `veercanvas/` tree into every site web root** — duplicate admin + services source.
5. **Do not rsync Android `app/build/` or AuthBuddy `target/`** to the host.

## Deploy reminder

```bash
# veer-ai: build Linux x86_64 elsewhere, then
#   cp target/release/veer-ai services/veer-ai/dist/veer-ai
SITE_ID=hbcsanyard EC2_KEY=~/Downloads/VeerSetuHost.pem ./deploy/remote-deploy.sh
```

Never `OVERRIDE_CATALOG=1` for Sanyard unless asked. Never replace live `data/`.
