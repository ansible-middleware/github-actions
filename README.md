# github-actions

Shared GitHub Actions workflows and helpers for
[ansible-middleware](https://github.com/ansible-middleware) Ansible collections
(for example `middleware_automation.keycloak`).

## Contents

| Path | Description |
| --- | --- |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | Lint, sanity, and molecule CI (reusable) |
| [`.github/workflows/cish.yml`](.github/workflows/cish.yml) | CI with optional Shell / podman scenarios |
| [`.github/workflows/docs.yml`](.github/workflows/docs.yml) | Collection docs / GitHub Pages |
| [`.github/workflows/release.yml`](.github/workflows/release.yml) | Release to Galaxy with SemVer + changelog |
| [`.github/actions/semver-bump/`](.github/actions/semver-bump/) | Composite action: calculate SemVer and stamp `galaxy.yml` |
| [`.github/actions/build_docs_changelogs/`](.github/actions/build_docs_changelogs/) | Changelog / docs helper action |
| [`.github/scripts/semver_bump.py`](.github/scripts/semver_bump.py) | SemVer calculation script (used by release) |

---

## Release workflow (`release.yml`)

Reusable workflow that collections call to publish a new version to Ansible Galaxy.

### What it does

1. Checks out the collection (full history + tags).
2. Calculates the next **SemVer** from antsibull changelog fragments (and new content).
3. Updates `galaxy.yml` if needed and commits `Prepare release X.Y.Z`.
4. Builds the collection (`ansible-galaxy collection build`).
5. Generates the changelog via `antsibull-changelog` (`collection-docs-action`).
6. Publishes to Ansible Galaxy.
7. Creates an annotated git tag `X.Y.Z` and a GitHub Release.
8. Bumps `galaxy.yml` to the next **patch** as a development placeholder and opens the matching Jira version when configured.

### Standards followed

Collections **MUST** use semantic versioning. This workflow follows:

- [Releasing collections](https://docs.ansible.com/projects/ansible/latest/community/collection_contributors/collection_releasing.html)
- [Releasing without release branches](https://docs.ansible.com/projects/ansible/latest/community/collection_contributors/collection_release_without_branches.html)
- [Distributing collections (SemVer summary)](https://docs.ansible.com/projects/ansible/latest/dev_guide/developing_collections_distributing.html)
- [antsibull-changelog categories](https://docs.ansible.com/projects/antsibull-changelog/changelogs/)
- [Semantic Versioning 2.0.0](https://semver.org/)

### Ansible SemVer rules

Given `MAJOR.MINOR.PATCH`:

| Release type | When to use | Allowed changes |
| --- | --- | --- |
| **patch** (`X.Y.Z`) | Backward-compatible fixes | Bug fixes / security fixes only. **No** new features, **no** deprecations. |
| **minor** (`X.Y.0`) | Backward-compatible additions | New features, modules/plugins, parameters; deprecations. **No** removals or behavior breaks. |
| **major** (`X.0.0`) | Incompatible API changes | Removals, breaking changes, incompatible behavior. |

From SemVer / Ansible:

- When **major** increments → reset minor and patch to `0`.
- When **minor** increments → reset patch to `0`.
- Version format is `X.Y.Z` with **no leading zeros** (for example `1.2.3`, not `01.2.3`).
- Git tags used for release are plain `X.Y.Z` (a `v` prefix on older tags is still recognized when reading history).

### Fragment → bump mapping

Bump level is taken from pending files in `changelogs/fragments/` (highest wins: major > minor > patch):

| Fragment section | SemVer bump | Rationale |
| --- | --- | --- |
| `breaking_changes` | **major** | Incompatible behavior; Ansible: major only |
| `removed_features` | **major** | Removals; Ansible: major only |
| `major_changes` | **minor** | Notable high-level changes — **not** SemVer major |
| `minor_changes` | **minor** | New features / options |
| `deprecated_features` | **minor** | Deprecations belong in minor, not patch |
| `add object.*` / `add plugin.*` | **minor** | Explicit new playbook/role/plugin fragments |
| `bugfixes` | **patch** | Backward-compatible fixes |
| `security_fixes` | **patch** | Security fixes (still BC) |
| `known_issues` | **patch** | Documentation of known issues |
| `trivial` | **patch** | Non-user-facing (tests, CI); omitted from published changelog |
| `release_summary` | *(no bump by itself)* | Written by the releaser; does not raise the level |

**Important:** antsibull `major_changes` ≠ SemVer major. SemVer major is `breaking_changes` / `removed_features`.

### New content without fragments

New modules and plugins often have **no** changelog fragment; antsibull picks them up from `version_added` at release time. To avoid under-bumping, auto mode also treats newly **added** paths since the last release tag under:

- `plugins/`
- `roles/`
- `playbooks/`

as a **minor** bump.

### How the version is chosen

```
base = highest SemVer git tag (3.1.2 or v3.1.2)
level = auto from fragments (+ new content), or explicit version_bump
calculated = bump(base, level)     # e.g. 3.1.2 + minor → 3.2.0
release = max(calculated, galaxy.yml version)
```

- If there is **no** tag yet, `galaxy.yml` is kept as-is (first release).
- If `galaxy.yml` was **manually** set higher (for example planned `4.0.0`), that value is kept.
- After publish, `galaxy.yml` becomes `release + patch` (for example `3.2.0` → `3.2.1`) as the next development placeholder. The **next** release recalculates from fragments again.

### Caller usage

```yaml
# In the collection repo, e.g. .github/workflows/release.yml
name: Release collection
on:
  workflow_dispatch:
    inputs:
      release_summary:
        description: Optional release summary for changelogs
        required: false
      version_bump:
        description: SemVer bump (auto | major | minor | patch)
        required: false
        default: auto

jobs:
  release:
    uses: ansible-middleware/github-actions/.github/workflows/release.yml@main
    with:
      collection_fqcn: middleware_automation.keycloak
      downstream_name: rhbk                    # optional, for Jira version naming
      release_summary: ${{ github.event.inputs.release_summary }}
      version_bump: ${{ github.event.inputs.version_bump || 'auto' }}
    secrets:
      galaxy_token: ${{ secrets.ANSIBLE_GALAXY_API_KEY }}
      jira_webhook: ${{ secrets.JIRA_WEBHOOK_CREATE_VERSION }}
```

#### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `collection_fqcn` | yes | — | Fully qualified collection name (`namespace.name`) |
| `downstream_name` | no | — | Downstream product short name for Jira (for example `rhbk`) |
| `release_summary` | no | — | Optional antsibull `release_summary` text |
| `version_bump` | no | `auto` | `auto` \| `major` \| `minor` \| `patch` |

#### Secrets

| Secret | Required | Description |
| --- | --- | --- |
| `galaxy_token` | yes | Ansible Galaxy API key |
| `jira_webhook` | no | Webhook to create the next Jira version |

#### Outputs

| Output | Description |
| --- | --- |
| `tag_version` | Version that was released (for example `3.2.0`) |

### Prerequisites in the collection repo

Before releasing, the collection should have:

- Valid `galaxy.yml` with a SemVer `version`
- `changelogs/` configured for antsibull-changelog (`config.yaml`, `fragments/`)
- Changelog fragments for merged PRs (except pure docs / new modules covered by `version_added`)
- CI green on the commit being released
- Permissions for the workflow to push commits/tags (`contents: write`)

### Local SemVer helper

Run from a collection checkout (with tags fetched):

```bash
# Show calculated release version (also logs base/level on stderr)
python3 /path/to/github-actions/.github/scripts/semver_bump.py --bump auto

# Force a level and stamp galaxy.yml
python3 /path/to/github-actions/.github/scripts/semver_bump.py --bump minor --update-galaxy

# Post-release WIP placeholder
python3 /path/to/github-actions/.github/scripts/semver_bump.py --next-patch 3.2.0
# → 3.2.1
```

Options:

| Flag | Description |
| --- | --- |
| `--bump auto\|major\|minor\|patch` | Bump policy (default `auto`) |
| `--galaxy PATH` | Path to `galaxy.yml` (default `galaxy.yml`) |
| `--fragments PATH` | Fragments dir (default `changelogs/fragments`) |
| `--update-galaxy` | Write the calculated version into `galaxy.yml` when it differs |
| `--github-output` | Write `TAG_VERSION` / `BUMP_LEVEL` / `galaxy_updated` to `$GITHUB_OUTPUT` |
| `--next-patch VERSION` | Print `VERSION` + patch only |

### Composite action (`semver-bump`)

Used internally by `release.yml`. It can also be called directly:

```yaml
- uses: ansible-middleware/github-actions/.github/actions/semver-bump@main
  id: semver
  with:
    version_bump: auto          # auto | major | minor | patch
    galaxy_file: galaxy.yml
    fragments_dir: changelogs/fragments
```

Outputs: `tag_version`, `bump_level`, `galaxy_updated`.

---

## Other reusable workflows

### `ci.yml` / `cish.yml`

Shared CI for ansible-lint, `ansible-test sanity`, and molecule across ansible-core versions. Collections call these with their FQCN / test options as today.

### `docs.yml`

Builds and publishes collection documentation (for example GitHub Pages).

---

## Development notes

- Release helpers are checked out from the **same commit** as the reusable workflow (`github.job_workflow_sha`), so a PR branch of this repo can be tested with:

  ```yaml
  uses: <owner>/github-actions/.github/workflows/release.yml@<branch-or-sha>
  ```

- Helpers are removed from the workspace before `ansible-galaxy collection build` so they are not packaged into the collection tarball.
- Post-release `galaxy.yml` bump is always **patch**; that is a WIP placeholder only. The next release’s SemVer is computed again from fragments and new content.
