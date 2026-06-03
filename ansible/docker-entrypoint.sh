#!/usr/bin/env bash
set -euo pipefail

ssh_source_dir="${SSH_SOURCE_DIR:-/seed-ssh}"
ssh_target_dir="${HOME:-/root}/.ssh"
ssh_auth_sock="${SSH_AUTH_SOCK:-${ssh_target_dir}/agent.sock}"
shared_passphrase="${TRESOR_SSH_KEY_PASSPHRASE:-}"
workspace_ansible_dir="${WORKSPACE_ANSIBLE_DIR:-/workspace/ansible}"
runtime_dir="${TRESOR_ANSIBLE_RUNTIME_DIR:-/root/.tresor-ansible}"

prepare_ansible_runtime() {
  local runtime_vault_dir="${runtime_dir}/vaults"
  local runtime_cfg="${runtime_dir}/ansible.cfg"
  local source_cfg="${workspace_ansible_dir}/ansible.cfg"
  local source_vault_dir="${workspace_ansible_dir}/vaults"
  local runtime_roles_path="${workspace_ansible_dir}/roles:~/.ansible/roles:/usr/share/ansible/roles:/etc/ansible/roles"
  local runtime_collections_path="~/.ansible/collections:/usr/share/ansible/collections"
  local runtime_vault_identity_list="qa@${runtime_vault_dir}/qa.vault, prod@${runtime_vault_dir}/prod.vault, vps@${runtime_vault_dir}/vps.vault"

  mkdir -p "${runtime_vault_dir}"
  chmod 700 "${runtime_dir}" "${runtime_vault_dir}"

  if [[ -d "${source_vault_dir}" ]]; then
    find "${source_vault_dir}" -maxdepth 1 -type f -print0 | while IFS= read -r -d '' src; do
      local base
      base="$(basename "${src}")"
      cp "${src}" "${runtime_vault_dir}/${base}"
      chmod 600 "${runtime_vault_dir}/${base}"
    done
  fi

  if [[ -f "${source_cfg}" ]]; then
    awk \
      -v roles_path="${runtime_roles_path}" \
      -v collections_path="${runtime_collections_path}" \
      -v vault_identity_list="${runtime_vault_identity_list}" \
      '
      function emit_defaults() {
        print "roles_path = " roles_path
        print "collections_path = " collections_path
        print "vault_identity_list = " vault_identity_list
      }
      /^\[defaults\][[:space:]]*$/ {
        if (in_defaults && !defaults_emitted) {
          emit_defaults()
          defaults_emitted = 1
        }
        in_defaults = 1
        defaults_seen = 1
        print
        next
      }
      /^\[/ {
        if (in_defaults && !defaults_emitted) {
          emit_defaults()
          defaults_emitted = 1
        }
        in_defaults = 0
        print
        next
      }
      {
        if (in_defaults && $0 ~ /^[[:space:]]*(roles_path|collections_path|vault_identity_list)[[:space:]]*=/) {
          next
        }
        print
      }
      END {
        if (!defaults_seen) {
          print "[defaults]"
        }
        if (!defaults_emitted) {
          emit_defaults()
        }
      }
      ' "${source_cfg}" > "${runtime_cfg}"
  else
    cat >"${runtime_cfg}" <<EOF
[defaults]
roles_path = ${runtime_roles_path}
collections_path = ${runtime_collections_path}
vault_identity_list = ${runtime_vault_identity_list}
EOF
  fi

  chmod 600 "${runtime_cfg}"
}

prepare_ssh_dir() {
  mkdir -p "${ssh_target_dir}"
  chmod 700 "${ssh_target_dir}"

  if [[ ! -d "${ssh_source_dir}" ]]; then
    return
  fi

  find "${ssh_source_dir}" -maxdepth 1 -type f -print0 | while IFS= read -r -d '' src; do
    base="$(basename "${src}")"
    dest="${ssh_target_dir}/${base}"
    cp "${src}" "${dest}"

    case "${base}" in
      *.pub)
        chmod 644 "${dest}"
        ;;
      known_hosts)
        chmod 644 "${dest}"
        ;;
      config)
        chmod 600 "${dest}"
        ;;
      *)
        chmod 600 "${dest}"
        ;;
    esac
  done
}

start_ssh_agent() {
  if [[ -S "${ssh_auth_sock}" ]]; then
    if SSH_AUTH_SOCK="${ssh_auth_sock}" ssh-add -l >/dev/null 2>&1; then
      export SSH_AUTH_SOCK="${ssh_auth_sock}"
      return
    fi
  fi

  rm -f "${ssh_auth_sock}"
  eval "$(ssh-agent -a "${ssh_auth_sock}" -s)" >/dev/null
  export SSH_AUTH_SOCK="${ssh_auth_sock}"
}

unlock_key_file() {
  local key_path="$1"
  local key_passphrase="$2"

  if [[ ! -f "${key_path}" ]]; then
    return
  fi

  if ssh-keygen -y -P "" -f "${key_path}" >/dev/null 2>&1; then
    return
  fi

  if [[ -z "${key_passphrase}" ]]; then
    return
  fi

  ssh-keygen -p -P "${key_passphrase}" -N "" -f "${key_path}" >/dev/null 2>&1 || true
}

load_key_into_agent() {
  local key_path="$1"
  local key_passphrase="$2"
  local askpass_script

  if [[ ! -f "${key_path}" ]]; then
    return
  fi

  if ssh-add -l | grep -F -- "${key_path}" >/dev/null 2>&1; then
    return
  fi

  if ssh-keygen -y -P "" -f "${key_path}" >/dev/null 2>&1; then
    SSH_ASKPASS_REQUIRE=never ssh-add "${key_path}" </dev/null >/dev/null 2>&1 || true
    return
  fi

  if [[ -z "${key_passphrase}" ]]; then
    echo "[tresor-ansible] key is encrypted and no passphrase env was provided: ${key_path}" >&2
    return
  fi

  askpass_script="$(mktemp)"
  cat >"${askpass_script}" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "${SSH_KEY_PASSPHRASE:-}"
EOF
  chmod 700 "${askpass_script}"

  env \
    DISPLAY=:0 \
    SSH_ASKPASS="${askpass_script}" \
    SSH_ASKPASS_REQUIRE=force \
    SSH_KEY_PASSPHRASE="${key_passphrase}" \
    setsid ssh-add "${key_path}" </dev/null >/dev/null 2>&1 || true

  rm -f "${askpass_script}"
}

prepare_ssh_dir
prepare_ansible_runtime
unlock_key_file "${ssh_target_dir}/id_ed25519_tresor" "${TRESOR_SSH_PASSPHRASE:-${shared_passphrase}}"
unlock_key_file "${ssh_target_dir}/id_ed25519_tresor_vps" "${TRESOR_VPS_SSH_PASSPHRASE:-${shared_passphrase}}"
start_ssh_agent
load_key_into_agent "${ssh_target_dir}/id_ed25519_tresor" "${TRESOR_SSH_PASSPHRASE:-${shared_passphrase}}"
load_key_into_agent "${ssh_target_dir}/id_ed25519_tresor_vps" "${TRESOR_VPS_SSH_PASSPHRASE:-${shared_passphrase}}"

cat <<'EOF'
[tresor-ansible] runtime ready
[tresor-ansible] launch the Satelite Watcher cockpit:
  python space-navigator.py
  python space-cli.py
[tresor-ansible] launch the Plane Watcher cockpit:
  python plane-navigator.py
  python plane-cli.py
[tresor-ansible] launch the Tresor Index cockpit:
  python tresor-index-cli.py
[tresor-ansible] launch the main control panel:
  python tresor-cli.py
EOF

exec "$@"
