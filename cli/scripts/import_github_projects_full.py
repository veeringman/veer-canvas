#!/usr/bin/env python3
import argparse
import json
import os
import pathlib
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.github.com"
USER_AGENT = "VeerLabs-Project-Importer/1.0"
LOGO_PATTERNS = [r"logo", r"icon", r"brand", r"mark"]
LOGO_EXTENSIONS = [".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"]
BADGE_PATTERNS = [r"license", r"badge", r"shield", r"build", r"ci", r"cover", r"github-actions", r"dependabot"]
SEARCH_DIRS = ["assets", "images", "img", "logo", "logos", "docs", "branding"]
DEFAULT_LOGO_PATH = "assets/default-project-logo.svg"
ADMIN_PRESERVED_FIELDS = (
    "enabled",
    "logoSize",
    "logoWidth",
    "logoHeight",
    "sortOrder",
    "name",
    "subtitle",
    "summary",
    "summaryFormat",
    "summaryAlign",
    "summarySize",
    "logo",
    "logoAlt",
    "tags",
    "status",
    "details",
    "reimport",
)
EXCLUSIONS_FILENAME = "catalog-exclusions.json"
PUBLIC_CATALOG_FILENAME = "projects-public.json"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or value.lower().replace(" ", "-")


def github_request(url: str, token: str | None = None, *, allow_unauth_retry: bool = True):
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        if token and allow_unauth_retry and exc.code in {401, 403}:
            print(f"GitHub token rejected; retrying without authentication for {url}", file=sys.stderr)
            return github_request(url, None, allow_unauth_retry=False)
        print(f"GitHub request failed ({exc.code}): {url}", file=sys.stderr)
        raise


def github_raw_request(url: str, token: str | None = None) -> str:
    headers = {"Accept": "application/vnd.github.v3.raw", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if token and exc.code in {401, 403}:
            print(f"GitHub token rejected; retrying without authentication for {url}", file=sys.stderr)
            return github_raw_request(url, None)
        raise


def fetch_authenticated_login(token: str | None = None) -> str | None:
    if not token:
        return None
    try:
        user = github_request(f"{API_BASE}/user", token)
        return user.get("login")
    except urllib.error.HTTPError:
        return None


def fetch_repos(owner: str, token: str | None = None) -> list[dict]:
    repos = []
    page = 1
    auth_login = fetch_authenticated_login(token)
    if token and auth_login == owner:
        base_url = f"{API_BASE}/user/repos?type=all"
    elif token:
        base_url = f"{API_BASE}/orgs/{owner}/repos?type=all"
    else:
        base_url = f"{API_BASE}/users/{owner}/repos"

    while True:
        separator = '&' if '?' in base_url else '?'
        url = f"{base_url}{separator}per_page=100&page={page}&sort=updated&direction=desc"
        try:
            page_repos = github_request(url, token)
        except urllib.error.HTTPError as exc:
            if exc.code in {403, 404}:
                print(f"GitHub repository listing unavailable ({exc.code}); using existing local catalog.", file=sys.stderr)
                return repos
            raise
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


def fetch_contents(full_name: str, path: str, token: str | None = None):
    try:
        url = f"{API_BASE}/repos/{full_name}/contents/{urllib.parse.quote(path, safe='')}"
        return github_request(url, token)
    except urllib.error.HTTPError:
        return None


def is_valid_logo_name(name: str) -> bool:
    lower = name.lower()
    if not any(lower.endswith(ext) for ext in LOGO_EXTENSIONS):
        return False
    if any(re.search(pattern, lower) for pattern in BADGE_PATTERNS):
        return False
    return True


def guess_logo_path(contents: list[dict]) -> list[str]:
    candidates = []
    for item in contents:
        if item.get("type") != "file":
            continue
        name = item.get("name", "")
        if is_valid_logo_name(name) and any(re.search(pattern, name.lower()) for pattern in LOGO_PATTERNS):
            candidates.append(item.get("download_url"))
    return candidates


def find_first_markdown_image(text: str) -> tuple[str | None, str | None]:
    # Prefer images appearing at the top of the README: before the first
    # section heading or within the first 40 lines. This reduces picking
    # badges or images embedded deeper in the README.
    lines = text.splitlines()
    first_heading_idx = None
    for idx, line in enumerate(lines):
        if re.match(r"^#{1,4}\s+", line):
            first_heading_idx = idx
            break
    search_limit = first_heading_idx if first_heading_idx is not None else min(len(lines), 40)
    for line in lines[:search_limit]:
        match = re.search(r"!\[([^\]]*)\]\(([^)]+)\)", line)
        if match:
            return match.group(1).strip(), match.group(2).strip()
    # fallback: scan entire README for any image
    for line in lines:
        match = re.search(r"!\[([^\]]*)\]\(([^)]+)\)", line)
        if match:
            return match.group(1).strip(), match.group(2).strip()
    return None, None


def resolve_readme_image_url(full_name: str, image_url: str, branch: str) -> str | None:
    if image_url.startswith("http://") or image_url.startswith("https://"):
        return image_url
    image_url = image_url.lstrip("./")
    image_url = image_url.lstrip("/")
    return f"https://raw.githubusercontent.com/{full_name}/{branch}/{image_url}"


def search_logo(full_name: str, token: str | None = None) -> tuple[str | None, list[str]]:
    candidates = []
    root_contents = fetch_contents(full_name, "", token) or []
    candidates.extend(guess_logo_path(root_contents))

    for directory in SEARCH_DIRS:
        contents = fetch_contents(full_name, directory, token)
        if not isinstance(contents, list):
            continue
        candidates.extend(guess_logo_path(contents))

    return (candidates[0] if candidates else None, candidates)


def download_url(url: str, dest_path: pathlib.Path, token: str | None = None) -> None:
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        data = response.read()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(data)


def markdown_paragraphs(text: str) -> list[str]:
    paragraphs = []
    current = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "":
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current).strip())
    return paragraphs


def markdown_sections(text: str) -> list[dict]:
    sections = []
    current = None
    for line in text.splitlines():
        match = re.match(r"^(#{1,4})\s+(.*)$", line)
        if match:
            if current:
                sections.append(current)
            current = {"title": match.group(2).strip(), "content": []}
            continue
        if current is not None:
            current["content"].append(line)
    if current:
        sections.append(current)
    return sections


def extract_markdown_list_items(text: str) -> list[str]:
    items = []
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r"^[>*\-+]\s+(.*)$", stripped)
        if match:
            current = match.group(1).strip()
            items.append(current)
        elif current and stripped:
            items[-1] = items[-1] + " " + stripped
    return items


def collapse_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def build_subtitle(repo: dict) -> str:
    parts = []
    language = (repo.get("language") or "").strip()
    if language:
        parts.append(language)

    topics = [topic for topic in (repo.get("topics") or []) if isinstance(topic, str) and topic.strip()]
    if topics:
        parts.append(" • ".join(topics[:3]))

    if parts:
        return " • ".join(parts)

    description = collapse_text(repo.get("description") or "")
    if description:
        return description[:90] + ("..." if len(description) > 90 else "")
    return "Open-source project"


def extract_summary(readme: str | None, repo: dict) -> str:
    if not readme:
        return repo.get("description") or ""

    cleaned = re.sub(r"^---[\s\S]*?---\s*", "", readme, count=1, flags=re.MULTILINE)
    cleaned = re.sub(r"<!--.*?-->", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", cleaned)

    paragraphs = []
    current = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        if re.match(r"^#{1,6}\s+", stripped):
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        if stripped.startswith("```") or stripped.startswith("|"):
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        if stripped.startswith(">"):
            continue
        if stripped.startswith("- ") and len(current) == 0:
            current.append(stripped[2:].strip())
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current).strip())

    for paragraph in paragraphs:
        cleaned_paragraph = collapse_text(paragraph)
        if len(cleaned_paragraph) >= 40:
            return cleaned_paragraph

    return repo.get("description") or ""


def build_details(readme: str | None, repo: dict) -> list[dict]:
    details = []
    summary = extract_summary(readme, repo)
    if summary:
        details.append({"title": "Project Overview", "body": summary})

    if readme:
        for section in markdown_sections(readme):
            title = section["title"].strip()
            body = "\n".join(section["content"]).strip()
            if not body:
                continue
            normalized_title = title.lower()
            if re.search(r"\b(feature|capabilit|benefit|advantage|what[\s-]*it does)\b", normalized_title):
                items = extract_markdown_list_items(body)
                if items:
                    details.append({"title": "Key Features", "items": items})
                    continue
            if re.search(r"\b(use case|application|architecture|installation|getting started|docs|overview|why)\b", normalized_title):
                details.append({"title": title, "body": body})
                continue
            if len(details) < 6:
                details.append({"title": title, "body": body})

    details.append({"title": "Repository", "body": repo.get("html_url", "")})
    if repo.get("homepage"):
        details.append({"title": "Homepage", "body": repo.get("homepage")})
    return details


def normalize_logo_path(slug: str, logo_path: str, site_root: pathlib.Path | None) -> str:
    if not logo_path or logo_path == DEFAULT_LOGO_PATH:
        return DEFAULT_LOGO_PATH
    if logo_path.startswith("miniapps/"):
        return logo_path
    if logo_path.startswith("assets/") and site_root:
        candidate = site_root / logo_path
        if candidate.exists():
            return logo_path
    rel = logo_path.replace("\\", "/").lstrip("./")
    if site_root and (site_root / "miniapps" / slug / rel).exists():
        return f"miniapps/{slug}/{rel}"
    if rel.startswith("assets/"):
        return f"miniapps/{slug}/{rel}"
    return f"miniapps/{slug}/assets/{pathlib.Path(rel).name}"


def enrich_project_defaults(project: dict, repo: dict | None = None, sort_index: int = 0) -> dict:
    project.setdefault("enabled", True)
    project.setdefault("logoSize", "md")
    project.setdefault("sortOrder", sort_index)
    if repo is not None:
        project.setdefault("private", bool(repo.get("private")))
        project.setdefault("repoUrl", repo.get("html_url"))
    project.setdefault("status", project.get("status") or ["Draft"])
    project.setdefault("tags", project.get("tags") or [])
    return project


def is_enabled(project: dict) -> bool:
    value = project.get("enabled", True)
    if value is False or value == 0:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "no", "off"}:
            return False
    return True


def load_catalog_exclusions(site_root: pathlib.Path | None) -> set[str]:
    if not site_root:
        return set()
    path = site_root / EXCLUSIONS_FILENAME
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {slug for slug in (data.get("deletedSlugs") or []) if isinstance(slug, str) and slug.strip()}


def wants_reimport(project: dict | None) -> bool:
    if not project:
        return False
    value = project.get("reimport", False)
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return False


def clear_reimport_flag(project: dict) -> dict:
    cleaned = dict(project)
    cleaned["reimport"] = False
    return cleaned


def is_already_imported(slug: str, site_root: pathlib.Path | None, catalog_index: dict[str, dict]) -> bool:
    if slug in catalog_index:
        return True
    if not site_root:
        return False
    return (site_root / "miniapps" / slug / "project.json").exists()


def preserve_admin_fields(existing: dict | None, incoming: dict, *, clear_reimport: bool = False) -> dict:
    if not existing:
        return incoming
    merged = dict(incoming)
    for key in ADMIN_PRESERVED_FIELDS:
        if key in existing:
            merged[key] = existing[key]
    if clear_reimport:
        merged["reimport"] = False
    return merged


def load_existing_project(slug: str, site_root: pathlib.Path | None, catalog_index: dict[str, dict]) -> dict | None:
    if slug in catalog_index:
        return catalog_index[slug]
    if not site_root:
        return None
    package_json = site_root / "miniapps" / slug / "project.json"
    if not package_json.exists():
        return None
    try:
        return json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def is_publicly_visible(project: dict, excluded: set[str] | None = None) -> bool:
    slug = project.get("slug")
    if excluded and isinstance(slug, str) and slug in excluded:
        return False
    return is_enabled(project)


def write_public_catalog(site_root: pathlib.Path, projects_path: pathlib.Path | None = None) -> int:
    projects_file = projects_path or (site_root / "projects.json")
    if not projects_file.exists():
        return 0
    projects = json.loads(projects_file.read_text(encoding="utf-8"))
    excluded = load_catalog_exclusions(site_root)
    visible = [project for project in projects if is_publicly_visible(project, excluded)]
    visible.sort(key=lambda item: (item.get("sortOrder", 9999), item.get("name", "")))
    write_json(site_root / PUBLIC_CATALOG_FILENAME, visible)
    return len(visible)


def sync_catalog_from_miniapps(site_root: pathlib.Path, projects_path: pathlib.Path) -> list[dict]:
    existing = []
    if projects_path.exists():
        existing = json.loads(projects_path.read_text(encoding="utf-8"))
    index = {entry["slug"]: entry for entry in existing if entry.get("slug")}
    excluded = load_catalog_exclusions(site_root)
    # Drop deleted/excluded catalog entries and leftover miniapp folders.
    for slug in list(index.keys()):
        if slug in excluded:
            del index[slug]
    miniapps_dir = site_root / "miniapps"
    if not miniapps_dir.exists():
        merged = list(index.values())
        merged.sort(key=lambda item: (item.get("sortOrder", 9999), item.get("name", "")))
        write_json(projects_path, merged)
        write_public_catalog(site_root, projects_path)
        return merged
    for package_dir in sorted(miniapps_dir.iterdir()):
        if not package_dir.is_dir():
            continue
        slug = package_dir.name
        if slug in excluded:
            continue
        package_json = package_dir / "project.json"
        if not package_json.exists():
            continue
        package_data = json.loads(package_json.read_text(encoding="utf-8"))
        package_data["slug"] = slug
        package_data["logo"] = normalize_logo_path(slug, package_data.get("logo", DEFAULT_LOGO_PATH), site_root)
        if slug in index:
            catalog_entry = index[slug]
            preserved = {k: catalog_entry[k] for k in ADMIN_PRESERVED_FIELDS if k in catalog_entry}
            merged_entry = enrich_project_defaults({**package_data, **preserved})
            merged_entry.update(preserved)
            # Catalog admin state wins for visibility.
            if "enabled" in catalog_entry:
                merged_entry["enabled"] = catalog_entry["enabled"]
            index[slug] = merged_entry
        else:
            index[slug] = enrich_project_defaults(package_data, sort_index=len(index))
    # Remove catalog entries whose miniapp package no longer exists (unless still marked somehow).
    live_slugs = {
        package_dir.name
        for package_dir in miniapps_dir.iterdir()
        if package_dir.is_dir() and (package_dir / "project.json").exists() and package_dir.name not in excluded
    }
    for slug in list(index.keys()):
        if slug not in live_slugs:
            del index[slug]
    merged = list(index.values())
    merged.sort(key=lambda item: (item.get("sortOrder", 9999), item.get("name", "")))
    write_json(projects_path, merged)
    write_public_catalog(site_root, projects_path)
    return merged


def merge_project_entries(existing: list[dict], new_entries: list[dict], replace: bool = False) -> list[dict]:
    index = {entry["slug"]: entry for entry in existing}
    for entry in new_entries:
        if entry["slug"] in index:
            if replace:
                preserved = {k: index[entry["slug"]][k] for k in ADMIN_PRESERVED_FIELDS if k in index[entry["slug"]]}
                merged = enrich_project_defaults({**entry, **preserved})
                merged.update(preserved)
                index[entry["slug"]] = merged
        else:
            index[entry["slug"]] = entry
    return list(index.values())


def write_json(path: pathlib.Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def make_package(
    repo: dict,
    output_dir: pathlib.Path,
    site_root: pathlib.Path | None,
    token: str | None = None,
    existing_project: dict | None = None,
) -> dict:
    slug = slugify(repo["name"])
    package_dir = output_dir / slug
    package_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = package_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    readme = fetch_readme(repo["full_name"], token)
    readme_logo_url = None
    if readme:
        (package_dir / "README.md").write_text(readme, encoding="utf-8")
        _, image_url = find_first_markdown_image(readme)
        if image_url:
            readme_logo_url = resolve_readme_image_url(repo["full_name"], image_url, repo["default_branch"])

    logo_url = None
    logo_candidates = []
    if readme_logo_url:
        logo_candidates.append(readme_logo_url)
        logo_url = readme_logo_url

    search_url, search_candidates = search_logo(repo["full_name"], token)
    logo_candidates.extend(search_candidates)
    if not logo_url:
        logo_url = search_url

    logo_path = DEFAULT_LOGO_PATH
    existing_logo = (existing_project or {}).get("logo")
    preserve_existing_logo = bool(
        existing_logo
        and existing_logo != DEFAULT_LOGO_PATH
        and not str(existing_logo).startswith("http")
    )
    if logo_url and not logo_url.endswith("/") and not preserve_existing_logo:
        filename = pathlib.Path(urllib.parse.urlparse(logo_url).path).name
        if is_valid_logo_name(filename):
            local_logo = assets_dir / filename
            try:
                download_url(logo_url, local_logo, token)
                if site_root:
                    logo_path = os.path.relpath(local_logo, site_root).replace(os.sep, "/")
                else:
                    logo_path = str(local_logo.relative_to(package_dir)).replace(os.sep, "/")
            except Exception as exc:
                print(f"Warning: failed to download logo {logo_url}: {exc}", file=sys.stderr)
    elif preserve_existing_logo:
        logo_path = existing_logo

    details = build_details(readme, repo)
    summary = extract_summary(readme, repo) or repo.get("description") or ""
    subtitle = build_subtitle(repo)
    project_json = enrich_project_defaults({
        "slug": slug,
        "name": repo.get("name"),
        "subtitle": subtitle,
        "summary": summary,
        "logo": normalize_logo_path(slug, logo_path, site_root),
        "logoAlt": f"{repo.get('name')} logo",
        "status": ["Draft"],
        "tags": repo.get("topics", []),
        "details": details,
    }, repo=repo)
    project_json = preserve_admin_fields(existing_project, project_json, clear_reimport=True)
    write_json(package_dir / "project.json", project_json)

    source = {
        "slug": slug,
        "repo": repo.get("html_url"),
        "default_branch": repo.get("default_branch"),
        "language": repo.get("language"),
        "topics": repo.get("topics", []),
        "logo_candidates": logo_candidates,
        "readme_logo_url": readme_logo_url,
    }
    write_json(package_dir / "source.json", source)

    return {
        "slug": slug,
        "name": repo.get("name"),
        "package_path": str(package_dir),
        "logo_found": logo_url is not None,
        "logo_url": logo_url,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import GitHub repositories into VeerLabs website packages and optional projects.json.")
    parser.add_argument("owner", help="GitHub owner or organization name")
    parser.add_argument("output_dir", nargs="?", default="imported_projects", help="Output directory for generated project packages")
    parser.add_argument("--site-root", default=None, help="If set, use this website root to integrate packages and compute logo paths")
    parser.add_argument("--projects-json", default=None, help="Path to website projects.json to update from generated packages")
    parser.add_argument("--limit", type=int, default=0, help="Limit the number of repositories processed")
    parser.add_argument("--public-only", action="store_true", help="Only process public repositories")
    parser.add_argument("--token", default=None, help="GitHub API token (or set GITHUB_TOKEN / GH_TOKEN)")
    parser.add_argument("--replace-existing", action="store_true", help="Replace existing entries in the target projects.json if slugs match")
    parser.add_argument("--sync-only", action="store_true", help="Only sync projects.json from miniapps/ without fetching GitHub")
    parser.add_argument("--write-public-catalog", action="store_true", help="Write projects-public.json from enabled projects in projects.json")
    parser.add_argument("--fetch-repos", action="store_true", help="Fetch repositories from GitHub (required for network import)")
    parser.add_argument(
        "--reimport-all",
        action="store_true",
        help="Force re-import of already imported projects (overwrites package content; admin fields still preserved)",
    )
    parser.add_argument(
        "--reimport-slugs",
        default="",
        help="Comma-separated slugs to force re-import (in addition to projects with reimport:true)",
    )
    parser.add_argument(
        "--only-slugs",
        default="",
        help="Comma-separated slugs to process (new or reimport); ignore other repos",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be imported without writing packages")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    output_dir = pathlib.Path(args.output_dir)
    site_root = pathlib.Path(args.site_root).resolve() if args.site_root else None
    if site_root and args.output_dir == "imported_projects":
        output_dir = site_root / "miniapps"
    if site_root and not output_dir.is_absolute():
        output_dir = output_dir.resolve()
    if args.dry_run:
        print("Dry run enabled; no package files will be written.")

    projects_path = pathlib.Path(args.projects_json) if args.projects_json else None
    if args.write_public_catalog:
        if not site_root:
            print("error: --write-public-catalog requires --site-root", file=sys.stderr)
            return 2
        count = write_public_catalog(site_root, projects_path)
        print(f"Wrote {count} enabled projects to {site_root / PUBLIC_CATALOG_FILENAME}")
        return 0
    if args.sync_only:
        if not site_root or not projects_path:
            print("error: --sync-only requires --site-root and --projects-json", file=sys.stderr)
            return 2
        merged = sync_catalog_from_miniapps(site_root, projects_path)
        print(f"Synced {len(merged)} projects into {projects_path}")
        return 0

    if not args.fetch_repos:
        print(
            "error: refusing to contact GitHub without --fetch-repos. "
            "Use --sync-only or --write-public-catalog for local catalog tasks.",
            file=sys.stderr,
        )
        return 2

    repos = fetch_repos(args.owner, token)
    if args.public_only:
        repos = [repo for repo in repos if not repo.get("private")]
    if args.limit > 0:
        repos = repos[: args.limit]

    catalog_index: dict[str, dict] = {}
    if projects_path and projects_path.exists():
        catalog_index = {entry["slug"]: entry for entry in json.loads(projects_path.read_text(encoding="utf-8")) if entry.get("slug")}
    excluded = load_catalog_exclusions(site_root)
    force_slugs = {slug.strip() for slug in args.reimport_slugs.split(",") if slug.strip()}
    only_slugs = {slugify(slug.strip()) for slug in args.only_slugs.split(",") if slug.strip()}
    if only_slugs:
        repos = [repo for repo in repos if slugify(repo.get("name", "")) in only_slugs]
        print(f"Filtered to {len(repos)} repositories matching --only-slugs")

    print(f"Found {len(repos)} repositories for {args.owner}")
    packages = []
    skipped = 0
    imported = 0
    for repo in repos:
        slug = slugify(repo["name"])
        if slug in excluded:
            print(f"Skipping {repo['full_name']} (admin deleted)")
            skipped += 1
            continue
        existing_project = load_existing_project(slug, site_root, catalog_index)
        already = is_already_imported(slug, site_root, catalog_index)
        force = (
            args.reimport_all
            or slug in force_slugs
            or wants_reimport(existing_project)
        )
        if already and not force:
            print(f"Skipping {repo['full_name']} (already imported; mark reimport in admin to refresh)")
            skipped += 1
            continue
        reason = "new" if not already else "reimport"
        print(f"Processing {repo['full_name']} ({reason})...")
        if args.dry_run:
            packages.append({"slug": slug, "name": repo.get("name"), "repo_url": repo.get("html_url"), "action": reason})
            imported += 1
            continue
        result = make_package(repo, output_dir, site_root, token, existing_project=existing_project)
        result["action"] = reason
        packages.append(result)
        # Keep in-memory index consistent for later catalog merges.
        try:
            package_data = json.loads(pathlib.Path(result["package_path"]).joinpath("project.json").read_text(encoding="utf-8"))
            catalog_index[slug] = package_data
        except (OSError, json.JSONDecodeError):
            pass
        imported += 1
        print(f"  -> package={result['package_path']} logo_found={result['logo_found']}")

    summary_path = pathlib.Path(args.output_dir) / "import-summary.json"
    if not args.dry_run:
        write_json(summary_path, packages)
        print(f"Import summary written to {summary_path}")
    print(f"Import complete: imported={imported} skipped={skipped}")

    if args.projects_json and not args.dry_run:
        projects_path = pathlib.Path(args.projects_json)
        if site_root:
            merged = sync_catalog_from_miniapps(site_root, projects_path)
            print(f"Synced catalog at {projects_path} with {len(merged)} projects")
        else:
            existing = []
            if projects_path.exists():
                existing = json.loads(projects_path.read_text(encoding="utf-8"))
            new_entries = []
            for package in packages:
                package_dir = pathlib.Path(package["package_path"])
                package_data = json.loads((package_dir / "project.json").read_text(encoding="utf-8"))
                new_entries.append(package_data)
            merged = merge_project_entries(existing, new_entries, replace=args.replace_existing)
            write_json(projects_path, merged)
            print(f"Updated projects.json at {projects_path} with {len(new_entries)} entries")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
