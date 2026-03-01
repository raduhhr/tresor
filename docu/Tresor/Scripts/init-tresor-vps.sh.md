init-tresor-vps.sh

set -euxo pipefail

\# 0) Packages Ansible expects  
apt update  
apt install -y python3 python3-apt sudo

\# 1) Create the 'ansible' user (no password, home dir)  
id -u ansible >/dev/null 2>&1 || adduser --disabled-password --gecos "" ansible  
usermod -aG sudo ansible

\# 2) Install SSH key for 'ansible'  
install -d -m 700 -o ansible -g ansible /home/ansible/.ssh  
\# Reuse the same key your-vps-provider injected for root:  
if \[ -f /root/.ssh/authorized_keys \]; then  
  install -m 600 -o ansible -g ansible /root/.ssh/authorized_keys /home/ansible/.ssh/authorized_keys  
else  
  echo "No /root/.ssh/authorized_keys to copy. Paste your public key now."  
  read -r -p "Public key: " PUBKEY  
  printf '%s\\n' "$PUBKEY" >/home/ansible/.ssh/authorized_keys  
  chown ansible:ansible /home/ansible/.ssh/authorized_keys  
  chmod 600 /home/ansible/.ssh/authorized_keys  
fi

\# 3) Passwordless sudo for Ansible (safe & common for automation)  
cat >/etc/sudoers.d/90-ansible-nopasswd <<'EOF'  
ansible ALL=(ALL) NOPASSWD:ALL  
EOF  
chmod 440 /etc/sudoers.d/90-ansible-nopasswd

\# 4) SSH hardening: disable password auth; keep root login via key only for now  
\# (your base play will later harden further)  
sed -i -E 's/^#?PasswordAuthentication .\*/PasswordAuthentication no/' /etc/ssh/sshd_config  
sed -i -E 's/^#?PermitRootLogin .\*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config  
systemctl restart ssh