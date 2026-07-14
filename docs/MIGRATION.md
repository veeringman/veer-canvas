# VeerCanvas migration

VeerCanvas was extracted from the [VeerSetu](https://github.com/veeringman/veersetu) monorepo into this repository on **2026-07-14**.

## Repository

- **GitHub:** [github.com/veeringman/veer-canvas](https://github.com/veeringman/veer-canvas)
- **Sample site:** `sites/veerlabs/` (VeerLabs Solutions)

## Deploy from this repo

```bash
git clone git@github.com:veeringman/veer-canvas.git
cd veer-canvas

SITE_ID=veerlabs EC2_KEY=./VeerSetuHost.pem ./deploy/remote-deploy.sh
```

Copy `EC2_SSH_KEY`, `EC2_HOST`, and `EC2_USER` GitHub Actions secrets from VeerSetu if you use CI deploy.

## VeerSetu cleanup

After the split, VeerSetu retains only the edge-fabric product (agents, relay, control plane). Website and CMS code live here.

## History

The initial commit history was preserved via `git subtree split --prefix=veercanvas` from VeerSetu.
