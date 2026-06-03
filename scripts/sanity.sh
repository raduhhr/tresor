#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
ansible_dir="${repo_root}/ansible"
inventory="${ANSIBLE_INVENTORY:-inventory/hosts.ini}"
sanity_ansible_config=""

if [ -z "${ANSIBLE_CONFIG:-}" ]; then
  sanity_ansible_config="$(mktemp --suffix=.cfg)"
  cat >"${sanity_ansible_config}" <<EOF
[defaults]
roles_path = ${ansible_dir}/roles:~/.ansible/roles:/usr/share/ansible/roles:/etc/ansible/roles
collections_path = ~/.ansible/collections:/usr/share/ansible/collections
hash_behaviour = replace
forks = 10
pipelining = True
host_key_checking = False
stdout_callback = default
callback_result_format = yaml
become_timeout = 30
EOF
  export ANSIBLE_CONFIG="${sanity_ansible_config}"
  trap 'rm -f "${sanity_ansible_config}"' EXIT
fi

section() {
  printf '\n==> %s\n' "$1"
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'missing required command: %s\n' "$1" >&2
    exit 127
  fi
}

section "tooling"
need_cmd python3
need_cmd ansible-playbook
need_cmd git

python3 --version
ansible-playbook --version | sed -n '1p'

section "python syntax"
python3 -m py_compile \
  "${ansible_dir}/tresor-cli.py" \
  "${ansible_dir}/tresor-cli-win.py" \
  "${ansible_dir}/space-navigator.py" \
  "${ansible_dir}/space-cli.py" \
  "${ansible_dir}/plane-navigator.py" \
  "${ansible_dir}/plane-cli.py"

section "ansible playbook syntax"
(
  cd "${ansible_dir}"
  python3 - "${inventory}" <<'PY'
from pathlib import Path
import subprocess
import sys

inventory = sys.argv[1]
inventory_args = [] if inventory in {"", "none", "NONE", "false", "FALSE"} else ["-i", inventory]
playbooks = sorted(Path("playbooks").rglob("*.yml")) + sorted(Path("playbooks").rglob("*.yaml"))
failed = []

print(f"playbooks: {len(playbooks)}")
for playbook in playbooks:
    result = subprocess.run(
        ["ansible-playbook", *inventory_args, "--syntax-check", str(playbook)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        print(f"\nFAIL {playbook}")
        print(result.stdout.rstrip())
        failed.append(str(playbook))

if failed:
    print(f"\nfailed playbooks: {len(failed)}")
    sys.exit(1)

print("ok")
PY
)

section "role test playbook syntax"
(
  cd "${ansible_dir}"
  python3 - <<'PY'
from pathlib import Path
import subprocess
import sys

tests = sorted(Path("roles").glob("*/tests/*.yml")) + sorted(Path("roles").glob("*/tests/*.yaml"))
failed = []

print(f"role tests: {len(tests)}")
for playbook in tests:
    result = subprocess.run(
        ["ansible-playbook", "--syntax-check", str(playbook)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        print(f"\nFAIL {playbook}")
        print(result.stdout.rstrip())
        failed.append(str(playbook))

if failed:
    print(f"\nfailed role tests: {len(failed)}")
    sys.exit(1)

print("ok")
PY
)

section "role structure"
(
  cd "${ansible_dir}"
  python3 - <<'PY'
from __future__ import annotations

from pathlib import Path
import sys

try:
    import yaml
except ImportError:
    print("missing Python package: pyyaml", file=sys.stderr)
    sys.exit(127)

roles_dir = Path("roles")
playbooks_dir = Path("playbooks")
roles = {path.name: path for path in roles_dir.iterdir() if path.is_dir()}
errors: list[str] = []
warnings: list[str] = []
role_refs: dict[str, set[str]] = {}

role_modules = {
    "import_role",
    "include_role",
    "ansible.builtin.import_role",
    "ansible.builtin.include_role",
}
task_include_modules = {
    "import_tasks",
    "include_tasks",
    "ansible.builtin.import_tasks",
    "ansible.builtin.include_tasks",
}
file_modules = {
    "copy": "files",
    "ansible.builtin.copy": "files",
    "template": "templates",
    "ansible.builtin.template": "templates",
}


def load_yaml(path: Path):
    try:
        with path.open("r", encoding="utf-8-sig") as fh:
            return yaml.safe_load(fh)
    except Exception as exc:
        errors.append(f"YAML parse failed: {path}: {exc}")
        return None


def normalize_role(role: str) -> str | None:
    if not role or "{{" in role:
        return None
    if role.startswith("roles/"):
        name = role.split("/", 1)[1]
        if name in roles:
            return name
    return role


def add_ref(role: str, source: Path) -> None:
    normalized = normalize_role(role)
    if not normalized:
        return
    role_refs.setdefault(normalized, set()).add(str(source))
    if normalized not in roles:
        errors.append(f"Missing role reference: {role} from {source}")


def module_arg(task: dict, module_names: set[str]):
    for module_name in module_names:
        if module_name in task:
            return module_name, task[module_name]
    return None, None


def extract_role_name(arg):
    if isinstance(arg, str):
        return arg
    if isinstance(arg, dict):
        name = arg.get("name") or arg.get("role")
        return name if isinstance(name, str) else None
    return None


def traverse(obj, source: Path, current_role: str | None = None, task_file: Path | None = None):
    if isinstance(obj, list):
        for item in obj:
            traverse(item, source, current_role, task_file)
        return
    if not isinstance(obj, dict):
        return

    if isinstance(obj.get("roles"), list):
        for item in obj["roles"]:
            add_ref(extract_role_name(item) or "", source)

    _, arg = module_arg(obj, role_modules)
    if arg is not None:
        add_ref(extract_role_name(arg) or "", source)

    _, arg = module_arg(obj, task_include_modules)
    if arg is not None and task_file:
        target = None
        if isinstance(arg, str):
            target = arg
        elif isinstance(arg, dict) and isinstance(arg.get("file"), str):
            target = arg["file"]
        if target and "{{" not in target:
            candidate = (task_file.parent / target).resolve()
            if not candidate.exists():
                errors.append(f"Missing task include: {task_file} -> {target}")

    if current_role:
        for module_name, subdir in file_modules.items():
            if module_name not in obj:
                continue
            arg = obj[module_name]
            src = arg.get("src") if isinstance(arg, dict) else None
            if (
                isinstance(src, str)
                and "{{" not in src
                and "://" not in src
                and not src.startswith("/")
            ):
                candidate = roles[current_role] / subdir / src
                if not candidate.exists():
                    errors.append(f"Missing {subdir} source: role {current_role}, {task_file}: {src}")

    for value in obj.values():
        traverse(value, source, current_role, task_file)


for role, path in sorted(roles.items()):
    if not (path / "tasks" / "main.yml").exists():
        warnings.append(f"Role has no tasks/main.yml: {role}")

    for yml in sorted(path.rglob("*.yml")) + sorted(path.rglob("*.yaml")):
        data = load_yaml(yml)
        is_task_file = "/tasks/" in yml.as_posix()
        traverse(data, yml, role, yml if is_task_file else None)

for playbook in sorted(playbooks_dir.rglob("*.yml")) + sorted(playbooks_dir.rglob("*.yaml")):
    traverse(load_yaml(playbook), playbook)

for role in sorted(set(roles) - set(role_refs)):
    warnings.append(f"Role not referenced by any parsed playbook/include_role: {role}")

print(f"roles: {len(roles)}")
for warning in warnings:
    print(f"WARN {warning}")

if errors:
    for error in errors:
        print(f"ERROR {error}")
    sys.exit(1)

print("ok")
PY
)

section "secret smoke scan"
(
  cd "${repo_root}"
  git grep -n -I \
    -e "BEGIN OPENSSH PRIVATE KEY" \
    -e "BEGIN RSA PRIVATE KEY" \
    -e "BEGIN EC PRIVATE KEY" \
    -e "discord.com/api/webhooks/" \
    -e "discordapp.com/api/webhooks/" \
    -e "AWS_SECRET_ACCESS_KEY=" \
    -e "GH_TOKEN=" \
    -e "GITHUB_TOKEN=" \
    -- . \
    ':!scripts/sanity.sh' \
    ':!ansible/inventory/**/*.vault.yml' \
    ':!ansible/inventory/**/vault.yml' && {
      printf 'secret smoke scan found tracked literal secret markers\n' >&2
      exit 1
    } || {
      status=$?
      if [ "${status}" -eq 1 ]; then
        printf 'ok\n'
      else
        exit "${status}"
      fi
    }
)

section "done"
printf 'sanity checks passed\n'
