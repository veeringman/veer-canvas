# CLI guide

Scripts under [`cli/scripts/`](../cli/scripts/).

## `create_site.py`

Scaffold a new website under `sites/<site_id>/` (theme from templates, `site.config.json`, next free admin port).

```bash
python cli/scripts/create_site.py my-catalog \
  --name "My Catalog" \
  --domain my-catalog.veerlabs.solutions \
  --github-owner veeringman

# Overwrite theme files if the folder already exists
python cli/scripts/create_site.py my-catalog --force ...
```

| Argument | Purpose |
|----------|---------|
| `site_id` | Folder name under `sites/` |
| `--name` | Display name |
| `--domain` | Primary hostname |
| `--github-owner` | Default GitHub org/user for import |
| `--force` | Replace theme files if site exists |

Prefer Site Studio on canvas for production create/deploy when the platform host is available; CLI is useful offline or in automation.

## `import_github_projects_full.py`

Full catalog integration: packages under `miniapps/`, updates `projects.json`, respects exclusions, can write the public catalog.

```bash
python cli/scripts/import_github_projects_full.py veeringman imported_projects \
  --site-root sites/veerlabs \
  --projects-json sites/veerlabs/projects.json \
  --fetch-repos \
  --write-public-catalog
```

Important flags:

| Flag | Purpose |
|------|---------|
| `--site-root` | Website root for package paths / logos |
| `--projects-json` | Catalog file to update |
| `--fetch-repos` | Actually call GitHub (required for network import) |
| `--write-public-catalog` | Emit `projects-public.json` from enabled entries |
| `--sync-only` | Rebuild catalog from existing `miniapps/` only |
| `--reimport-all` | Force re-import packages (admin fields preserved where possible) |
| `--reimport-slugs` | Comma-separated forced reimports |
| `--only-slugs` | Limit processing to listed slugs |
| `--public-only` | Skip private repos |
| `--token` / `GITHUB_TOKEN` / `GH_TOKEN` | Auth for private repos |
| `--dry-run` | Print plan without writing |

**Default behavior:** already-imported projects are skipped unless reimport is marked in admin or via flags.

## `import_github_projects.py`

Lightweight helper: fetch repos into package dirs + `import-summary.json` without the full site-root integration path. Prefer the **full** importer for VeerCanvas sites.

## Related

- [ADMIN_MANUAL.md](ADMIN_MANUAL.md) · [DEPLOY.md](DEPLOY.md) · [cli/README.md](../cli/README.md)
