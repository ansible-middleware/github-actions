# ansible-middleware/github-actions

Shared GitHub Actions for ansible-middleware collections.

## Actions

### `.github/vale-lint` — Vale Prose Lint

Spell and grammar checking for ansible-middleware collections using [Vale](https://vale.sh/).
It runs two checks in every pull request:

1. **Prose files** — Vale lints all Markdown and RST files using the project's `.vale.ini`.
2. **Ansible YAML prose fields** — Vale lints the human-readable fields (`name:`, `msg:`, `description:`, etc.) from task files, handler files, playbooks, and Molecule scenarios.

#### Usage

Add a workflow file to your collection repository:

```yaml
---
name: Prose Lint

on:
  pull_request:

jobs:
  vale:
    name: Spelling and Grammar check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - uses: ansible-middleware/github-actions/.github/vale-lint@main
```

You can pin to a specific Vale version or raise the alert threshold:

```yaml
      - uses: ansible-middleware/github-actions/.github/vale-lint@main
        with:
          vale-version: '3.15.1'
          min-alert-level: error
```

#### Inputs

| Input | Description | Default |
|---|---|---|
| `vale-version` | Vale version to install | `3.15.1` |
| `min-alert-level` | Minimum alert level to report (`suggestion`, `warning`, `error`) | `warning` |

#### Per-project configuration

This shared action does not ship a `.vale.ini` — each collection must provide one at its own repository root. A minimal working example:

```ini
StylesPath = .github/styles
MinAlertLevel = suggestion
Vocab = Base
Packages = write-good, proselint

[*.md]
BasedOnStyles = write-good, proselint
Vale.Spelling = warning
proselint.Annotations = NO
TokenIgnores = (?:[a-z][a-z\d]*_)+[a-z\d_]+

[*.rst]
BasedOnStyles = write-good, proselint
Vale.Spelling = warning
proselint.Annotations = NO
TokenIgnores = (?:[a-z][a-z\d]*_)+[a-z\d_]+
```

`TokenIgnores` is important: it tells Vale to skip `snake_case` tokens (e.g. `jboss_home`) as a whole, rather than splitting at underscores and flagging `jboss` and `home` as misspelled words.

`vale sync` downloads the declared `Packages` at runtime; no vendoring is required.

#### Vocabulary — shared and per-project

The action ships a shared vocabulary at `.github/vale-lint/vocabularies/accept.txt` containing ansible-middleware technical terms (WildFly, JBoss, EAP, Keycloak, FQCN, idempotency, etc.). This vocabulary is automatically merged into the collection's `.github/styles/config/vocabularies/Base/accept.txt` during every run.

To add project-specific accepted terms, create `.github/styles/config/vocabularies/Base/accept.txt` in your collection repository and commit it. One word per line. The action appends the shared vocabulary on top of whatever is already there.

#### Spell checking — Hunspell dictionary

For comprehensive spell checking that recognises common English words and proper nouns, configure Vale to use the system Hunspell dictionary (installed by this action):

```ini
[*.md]
Vale.Spelling.aff = /usr/share/hunspell/en_US.aff
Vale.Spelling.dic = /usr/share/hunspell/en_US.dic
```

Without this, Vale falls back to its built-in word list, which may flag common English names. Words genuinely absent from the Hunspell dictionary (middleware product names, Ansible jargon) should go into the project's `accept.txt` instead.

#### Task-name rule suppressions

The action ships `.github/vale-lint/vale-tasks.ini`, which suppresses rules that produce too many false positives for short imperative strings (such as `write-good.TooWordy` and `write-good.Weasel`). This config is merged with the project's `.vale.ini` only for the YAML field check — the full prose linting step (`vale .`) is unaffected.

To override the defaults, create `.github/vale-tasks.ini` in your collection repository. It will take precedence over the shared action config:

```ini
# .github/vale-tasks.ini — project-specific task name rule tuning
write-good.TooWordy = NO
write-good.Weasel = NO
```

#### Files checked

| Source | Fields / Files |
|---|---|
| Vale | All `*.md` and `*.rst` files (and any other types configured in `.vale.ini`) |
| Python script | `name:`, `msg:`, `fail_msg:`, `success_msg:` in `roles/**/tasks/`, `roles/**/handlers/`, `playbooks/`, and `molecule/` YAML files |
| Python script | `description:`, `short_description:` in `galaxy.yml`, `roles/*/meta/main.yml`, and `roles/*/meta/argument_specs.yml` |
