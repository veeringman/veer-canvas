# Migrating VeerCanvas to a standalone repository

The VeerCanvas platform currently lives under `veercanvas/` in the VeerSetu monorepo. It is intended to become **`veeringman/veer-canvas`** on GitHub.

## Option A — Publish `veercanvas/` as a new repo (recommended)

```bash
# On a machine with git and GitHub CLI
cd /path/to/veersetu
git subtree split --prefix=veercanvas -b veercanvas-only

mkdir ../veer-canvas && cd ../veer-canvas
git init
git pull /path/to/veersetu veercanvas-only
git remote add origin git@github.com:veeringman/veer-canvas.git
git push -u origin main
```

## Option B — Copy directory

```bash
cp -a veersetu/veercanvas/ veer-canvas/
cd veer-canvas
git init && git add . && git commit -m "Initial VeerCanvas platform"
git remote add origin git@github.com:veeringman/veer-canvas.git
git push -u origin main
```

## After split

1. Update EC2 deploy to clone/pull `veer-canvas` instead of `veersetu/veerabs_website`
2. Point CI secrets to `veercanvas/deploy/remote-deploy.sh`
3. In VeerSetu, replace website tree with a submodule or link:

   ```bash
   git submodule add git@github.com:veeringman/veer-canvas.git veercanvas
   ```

## VeerSetu repo cleanup

After the split, VeerSetu should retain only:

- VeerSetu product code (agents, relay, control plane)
- Optional submodule pointer to `veer-canvas` for the VeerLabs site
- No duplicate `veerabs_website/` or website deploy scripts
