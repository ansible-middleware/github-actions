"""Check grammar and spelling in Ansible YAML prose fields using Vale."""
import glob
import os
import re
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:
    print("PyYAML not available, skipping YAML prose check.", file=sys.stderr)
    sys.exit(0)

PROJECT_ROOT = os.getcwd()
ACCEPT_TXT = os.path.join(
    PROJECT_ROOT, ".github", "styles", "config", "vocabularies", "Base", "accept.txt"
)


def _find_vale_config():
    """Walk up from the working directory to find .vale.ini, mirroring Vale's own discovery."""
    current = PROJECT_ROOT
    while True:
        candidate = os.path.join(current, '.vale.ini')
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            raise FileNotFoundError(
                "No .vale.ini found in or above the project root. "
                "Each collection must provide a .vale.ini at the repository root."
            )
        current = parent


try:
    VALE_CONFIG = _find_vale_config()
except FileNotFoundError as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)

JINJA2_RE = re.compile(r'\{\{[^}]+\}\}')

# Prose-bearing keys extracted from task/handler/playbook/molecule YAML files.
TASK_KEYS = frozenset({'name', 'msg', 'fail_msg', 'success_msg'})

# Prose-bearing keys extracted from galaxy.yml and role meta/argument_specs files.
META_KEYS = frozenset({'description', 'short_description'})

# Task-specific Vale config: project override takes precedence over action default.
_ACTION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_TASKS_INI = os.path.join(PROJECT_ROOT, '.github', 'vale-tasks.ini')
_ACTION_TASKS_INI = os.path.join(_ACTION_DIR, 'vale-tasks.ini')
TASKS_INI = _PROJECT_TASKS_INI if os.path.exists(_PROJECT_TASKS_INI) else _ACTION_TASKS_INI


def _load_accepted_terms():
    """Load accepted spelling terms from the merged Vale vocabulary file."""
    try:
        with open(ACCEPT_TXT) as f:
            return {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        return set()


ACCEPTED_TERMS = _load_accepted_terms()


def _build_tasks_config():
    """Return path to a temp Vale config: project base merged with task suppressions."""
    with open(VALE_CONFIG) as f:
        base = f.read()
    extra = ''
    if os.path.exists(TASKS_INI):
        with open(TASKS_INI) as f:
            extra = f.read()
    config_dir = os.path.dirname(os.path.abspath(VALE_CONFIG))
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.ini', dir=config_dir, delete=False
    ) as f:
        f.write(base)
        if extra:
            f.write('\n' + extra)
        return f.name


def get_prose_fields(filepath, keys):
    results = []
    try:
        with open(filepath) as f:
            raw = f.read()
        data = yaml.safe_load(raw)
        lines = raw.splitlines()

        def _collect(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in keys:
                        texts = [v] if isinstance(v, str) else (v if isinstance(v, list) else [])
                        for text in texts:
                            if not isinstance(text, str) or not text.strip():
                                continue
                            text = text.strip().strip('"\'')
                            needle = text.split('{{', maxsplit=1)[0].strip()[:30]
                            lineno = next(
                                (i + 1 for i, l in enumerate(lines)
                                 if f'{k}:' in l and needle and needle in l),
                                0,
                            )
                            results.append((lineno, text))
                    else:
                        _collect(v)
            elif isinstance(obj, list):
                for item in obj:
                    _collect(item)

        _collect(data)
    except Exception:
        pass
    return results


def is_accepted(message, rule):
    """Return True if the finding should be suppressed."""
    if rule == "Vale.Spelling":
        # Extract the flagged word from "Did you really mean 'X'?"
        m = re.search(r"'([^']+)'", message)
        if m and m.group(1) in ACCEPTED_TERMS:
            return True
    return False


def vale_check(text, config):
    """Run Vale on a single string using the given config, returning filtered findings."""
    clean = JINJA2_RE.sub('VALUE', text)
    # Replace snake_case tokens (e.g. jboss_home) with a placeholder so Vale
    # does not flag each underscore-joined segment as a misspelled word.
    clean = re.sub(r'\b(?:[a-z][a-z\d]*_)+[a-z\d_]+\b', 'VARNAME', clean)

    # Vale requires a file path; it does not read from stdin.
    # Place the temp file beside the config so Vale resolves StylesPath correctly.
    config_dir = os.path.dirname(os.path.abspath(config))
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.md', dir=config_dir, delete=False
    ) as tmp:
        tmp.write(clean + '\n')
        tmp_path = tmp.name

    findings = []
    try:
        result = subprocess.run(
            ['vale', '--config', config, '--output=line',
             '--minAlertLevel=warning', tmp_path],
            capture_output=True, text=True, check=False,
        )
        for line in result.stdout.strip().splitlines():
            # Format: "path:line:col:rule:message"
            parts = line.split(':')
            if len(parts) < 5:
                continue
            rule = parts[3].strip()
            message = ':'.join(parts[4:]).strip()
            if not is_accepted(message, rule):
                findings.append((rule, message))
    finally:
        os.unlink(tmp_path)

    return findings


def _check_files(file_list, keys, config):
    found_issues = False
    for filepath in file_list:
        for lineno, text in get_prose_fields(filepath, keys):
            for rule, message in vale_check(text, config):
                found_issues = True
                print(f"{filepath}:{lineno}: {message} [{text!r}]")
    return found_issues


def main():
    task_files = sorted(set(
        glob.glob('roles/**/tasks/**/*.yml', recursive=True) +
        glob.glob('roles/**/tasks/*.yml', recursive=True) +
        glob.glob('roles/**/handlers/**/*.yml', recursive=True) +
        glob.glob('roles/**/handlers/*.yml', recursive=True) +
        glob.glob('playbooks/**/*.yml', recursive=True) +
        glob.glob('playbooks/*.yml') +
        glob.glob('molecule/**/*.yml', recursive=True) +
        glob.glob('molecule/*.yml')
    ))

    meta_files = sorted(set(
        glob.glob('galaxy.yml') +
        glob.glob('roles/*/meta/main.yml') +
        glob.glob('roles/*/meta/argument_specs.yml')
    ))

    tasks_config = _build_tasks_config()
    try:
        found_issues = _check_files(task_files, TASK_KEYS, tasks_config)
        found_issues = _check_files(meta_files, META_KEYS, tasks_config) or found_issues
    finally:
        os.unlink(tasks_config)

    if found_issues:
        print("Vale found spelling or grammar issues in YAML prose fields.", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
