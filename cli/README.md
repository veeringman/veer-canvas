# VeerCanvas CLI

Import, scaffold, and catalog tooling.

| Script | Purpose |
|--------|---------|
| `scripts/create_site.py` | Scaffold `sites/<id>/` from templates |
| `scripts/import_github_projects_full.py` | Full GitHub → miniapps + `projects.json` |
| `scripts/import_github_projects.py` | Lightweight package fetch (prefer full importer for sites) |

```bash
python cli/scripts/create_site.py my-catalog --name "My Catalog" --domain my-catalog.veerlabs.solutions
python cli/scripts/import_github_projects_full.py veeringman imported_projects \
  --site-root sites/veerlabs \
  --projects-json sites/veerlabs/projects.json \
  --fetch-repos \
  --write-public-catalog
```

Details and flags: [docs/CLI.md](../docs/CLI.md).
