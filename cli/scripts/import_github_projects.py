#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.github.com"
USER_AGENT = "VeerLabs-Project-Importer/1.0"
LOGO_PATTERNS = [r"logo", r"icon", r"brand", r"mark"]
LOGO_EXTENSIONS = [".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or value.lower().replace(" ", "-")


def github_request(url: str, token: str | None = None) -> dict:
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        print(f"GitHub request failed ({exc.code}): {url}", file=sys.stderr)
        raise


def github_raw_request(url: str, token: str | None = None) -> str:
    headers = {"Accept": "application/vnd.github.v3.raw", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_repos(owner: str, token: str | None = None) -> list[dict]:
    repos = []
    page = 1
    while True:
        url = f"{API_BASE}/users/{owner}/repos?per_page=100&page={page}&sort=updated&direction=desc"
        page_repos = github_request(url, token)
        if not page_repos:
            break
        repos.extend(page_repos)
        if len(page_repos) < 100:
            break
        page += 1
    return repos


def fetch_readme(full_name: str, token: str | None = None) -> str | None:
    try:
        url = f"{API_BASE}/repos/{full_name}/readme"
        return github_raw_request(url, token)
    except urllib.error.HTTPError:
        return None


def fetch_contents(full_name: str, path: str, token: str | None = None) -> list[dict] | None:
    try:
        url = f"{API_BASE}/repos/{full_name}/contents/{urllib.parse.quote(path)}"
        return github_request(url, token)
    except urllib.error.HTTPError:
        return None


def guess_logo_path(contents: list[dict]) -> str | None:
    candidates = []
    for item in contents:
        if item.get("type") != "file":
            continue
        name = item.get("name", "").lower()
        if any(name.endswith(ext) for ext in LOGO_EXTENSIONS) and any(re.search(pattern, name) for pattern in LOGO_PATTERNS):
            candidates.append(item.get("download_url"))
    return candidates[0] if candidates else None


def search_logo(full_name: str, default_branch: str, token: str | None = None) -> tuple[str | None, list[str]]:
    root = fetch_contents(full_name, "", token) or []
    candidates = []
    root_logo = guess_logo_path(root)
    if root_logo:
        return root_logo, [root_logo]

    search_dirs = ["assets", "images", "img", "logo", "docs", "branding"]
    for directory in search_dirs:
        contents = fetch_contents(full_name, directory, token)
        if not isinstance(contents, list):
            continue
        logo = guess_logo_path(contents)
        if logo:
            candidates.append(logo)
    return candidates[0] if candidates else None, candidates


def download_url(url: str, dest_path: str, token: str | None = None) -> None:
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        content = response.read()
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as fp:
        fp.write(content)


def make_package(repo: dict, output_dir: str, token: str | None = None) -> dict:
    slug = slugify(repo["name"])
    path = os.path.join(output_dir, slug)
    os.makedirs(path, exist_ok=True)
    meta = {
        "slug": slug,
        "name": repo.get("name"),
        "subtitle": repo.get("description") or "",
        "summary": repo.get("description") or "",
        "repo_url": repo.get("html_url"),
        "homepage": repo.get("homepage") or "",
        "topics": repo.get("topics", []),
        "default_branch": repo.get("default_branch"),
        "source": {
            "full_name": repo.get("full_name"),
            "private": repo.get("private"),
            "language": repo.get("language"),
        },
    }

    readme = fetch_readme(repo["full_name"], token)
    if readme:
        with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as fp:
            fp.write(readme)
        meta["readme_snippet"] = readme.strip().split("\n\n")[0][:800]

    logo_url, candidates = search_logo(repo["full_name"], repo["default_branch"], token)
    meta["logo_candidates"] = candidates
    if logo_url:
        dest = os.path.join(path, "assets", os.path.basename(urllib.parse.urlparse(logo_url).path))
        download_url(logo_url, dest, token)
        meta["logo"] = os.path.relpath(dest, path).replace(os.sep, "/")
    else:
        meta["logo"] = "assets/<logo-file>"

    project_json = {
        "slug": slug,
        "name": repo.get("name"),
        "subtitle": repo.get("description") or "",
        "summary": repo.get("description") or "",
        "logo": meta["logo"],
        "logoAlt": f"{repo.get('name')} logo",
        "status": ["Draft"],
        "tags": repo.get("topics", []),
        "details": [
            {"title": "Project Overview", "body": repo.get("description") or ""},
            {"title": "Repository", "body": repo.get("html_url")}
        ]
    }

    with open(os.path.join(path, "project.json"), "w", encoding="utf-8") as fp:
        json.dump(project_json, fp, indent=2)
    with open(os.path.join(path, "source.json"), "w", encoding="utf-8") as fp:
        json.dump(meta, fp, indent=2)

    return {
        "slug": slug,
        "name": repo.get("name"),
        "logo_found": bool(logo_url),
        "logo_url": logo_url,
        "package_path": path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import GitHub repositories into VeerLabs website project packages.")
    parser.add_argument("owner", help="GitHub owner or organization name")
    parser.add_argument("output_dir", help="Output directory for generated project packages")
    parser.add_argument("--limit", type=int, default=0, help="Limit the number of repos to process")
    parser.add_argument("--public-only", action="store_true", help="Only process public repositories")
    parser.add_argument("--token", default=None, help="GitHub API token (also read from GITHUB_TOKEN or GH_TOKEN)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repos = fetch_repos(args.owner, token)
    if args.public_only:
        repos = [repo for repo in repos if not repo.get("private")]
    if args.limit > 0:
        repos = repos[: args.limit]

    print(f"Found {len(repos)} repositories for {args.owner}")
    os.makedirs(args.output_dir, exist_ok=True)
    summary = []
    for repo in repos:
        print(f"Processing {repo['full_name']}...")
        item = make_package(repo, args.output_dir, token)
        summary.append(item)
        print(f"  -> package={item['package_path']} logo_found={item['logo_found']}")

    with open(os.path.join(args.output_dir, "import-summary.json"), "w", encoding="utf-8") as fp:
        json.dump(summary, fp, indent=2)
    print(f"Import complete. Summary written to {os.path.join(args.output_dir, 'import-summary.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
