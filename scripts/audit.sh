#!/usr/bin/env bash
# ============================================================================
# tresor-security-audit.sh — Post-exposure security audit for Tresor homelab
#
# Run from your Ansible control machine (Legion):
#   chmod +x tresor-security-audit.sh
#   ./tresor-security-audit.sh
#
# Requires: ssh access to tresor (192.168.1.100) and tresor-vps (1.2.3.4)
# ============================================================================
set -uo pipefail

RED='\033[0;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
CYN='\033[0;36m'
RST='\033[0m'

PASS=0; WARN=0; FAIL=0; INFO=0

pass()  { PASS=$((PASS+1)); echo -e "  ${GRN}[PASS]${RST} $1"; }
warn()  { WARN=$((WARN+1)); echo -e "  ${YEL}[WARN]${RST} $1"; }
fail()  { FAIL=$((FAIL+1)); echo -e "  ${RED}[FAIL]${RST} $1"; }
info()  { INFO=$((INFO+1)); echo -e "  ${CYN}[INFO]${RST} $1"; }
header(){ echo -e "\n${CYN}━━━ $1 ━━━${RST}"; }

TRESOR="ansible@192.168.1.100"
VPS="ansible@1.2.3.4"
SSH_TRESOR="ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i ~/.ssh/id_ed25519_homelab $TRESOR"
SSH_VPS="ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i ~/.ssh/id_ed25519_homelab_vps $VPS"

echo -e "${CYN}╔══════════════════════════════════════════════╗${RST}"
echo -e "${CYN}║     Tresor Security Audit — $(date +%Y-%m-%d)      ║${RST}"
echo -e "${CYN}╚══════════════════════════════════════════════╝${RST}"

# ============================================================================
header "1. TRESOR — SSH & System"
# ============================================================================

# SSH reachability
if $SSH_TRESOR "true" 2>/dev/null; then
  pass "Tresor SSH reachable"
else
  fail "Cannot SSH to Tresor — remaining checks will fail"
  exit 1
fi

# Root login disabled
SSHD_ROOT=$($SSH_TRESOR "sudo sshd -T 2>/dev/null | grep -i '^permitrootlogin'" || echo "unknown")
if echo "$SSHD_ROOT" | grep -qi "no"; then
  pass "SSH root login disabled"
else
  fail "SSH root login NOT disabled: $SSHD_ROOT"
fi

# Password auth disabled
SSHD_PASS=$($SSH_TRESOR "sudo sshd -T 2>/dev/null | grep -i '^passwordauthentication'" || echo "unknown")
if echo "$SSHD_PASS" | grep -qi "no"; then
  pass "SSH password auth disabled"
else
  fail "SSH password auth NOT disabled: $SSHD_PASS"
fi

# Fail2ban running
if $SSH_TRESOR "systemctl is-active fail2ban" 2>/dev/null | grep -q "active"; then
  pass "Fail2ban active on Tresor"
else
  warn "Fail2ban not active on Tresor (LAN-only host, lower risk)"
fi

# Unattended upgrades
if $SSH_TRESOR "test -f /etc/apt/apt.conf.d/20auto-upgrades && grep -q 'Unattended-Upgrade.*1' /etc/apt/apt.conf.d/20auto-upgrades" 2>/dev/null; then
  pass "Unattended upgrades enabled"
else
  warn "Unattended upgrades may not be configured"
fi

# ============================================================================
header "2. TRESOR — Docker Daemon Security"
# ============================================================================

# Docker data root on SSD
DOCKER_ROOT=$($SSH_TRESOR "docker info 2>/dev/null | grep 'Docker Root Dir'" || echo "unknown")
if echo "$DOCKER_ROOT" | grep -q "/mnt/ssd"; then
  pass "Docker data-root on SSD: $DOCKER_ROOT"
else
  info "Docker root: $DOCKER_ROOT"
fi

# User namespace remapping
USERNS=$($SSH_TRESOR "docker info 2>/dev/null | grep -i 'userns'" || echo "none")
if echo "$USERNS" | grep -qi "remap"; then
  pass "Docker userns-remap enabled"
else
  warn "Docker userns-remap disabled — containers share host UID space"
fi

# No containers running as --privileged
PRIV=$($SSH_TRESOR "docker ps -q | xargs -I{} docker inspect --format '{{.Name}} privileged={{.HostConfig.Privileged}}' {} 2>/dev/null" || echo "")
if echo "$PRIV" | grep -q "privileged=true"; then
  fail "Privileged containers found:\n$PRIV"
else
  pass "No privileged containers running"
fi

# ============================================================================
header "3. TRESOR — Container Port Bindings (the big one)"
# ============================================================================

echo -e "  Checking for 0.0.0.0 bindings (exposed to all interfaces)..."
PORTS=$($SSH_TRESOR "docker ps --format '{{.Names}}\t{{.Ports}}'" 2>/dev/null || echo "")

while IFS=$'\t' read -r name ports; do
  [[ -z "$name" ]] && continue
  if echo "$ports" | grep -q "0\.0\.0\.0:"; then
    fail "$name binds to 0.0.0.0 → $ports"
  elif echo "$ports" | grep -q "192\.168\."; then
    pass "$name bound to LAN IP only"
  elif echo "$ports" | grep -q "10\.66\.66\."; then
    pass "$name bound to WireGuard IP only"
  elif echo "$ports" | grep -q "127\.0\.0\.1:"; then
    pass "$name bound to localhost only"
  elif [[ -z "$ports" ]]; then
    info "$name — no published ports (internal network only)"
  else
    info "$name — ports: $ports"
  fi
done <<< "$PORTS"

# ============================================================================
header "4. TRESOR — Docker Network Isolation"
# ============================================================================

# Check internal_net is actually internal
INTERNAL=$($SSH_TRESOR "docker network inspect internal_net --format '{{.Internal}}'" 2>/dev/null || echo "unknown")
if [[ "$INTERNAL" == "true" ]]; then
  pass "internal_net is marked internal (no outbound)"
else
  fail "internal_net is NOT internal: $INTERNAL"
fi

# Check public_net is not internal
PUBLIC=$($SSH_TRESOR "docker network inspect public_net --format '{{.Internal}}'" 2>/dev/null || echo "unknown")
if [[ "$PUBLIC" == "false" ]]; then
  pass "public_net is external (as expected for Traefik/Cloudflared)"
else
  info "public_net internal flag: $PUBLIC"
fi

# ============================================================================
header "5. TRESOR — DOCKER-USER Firewall Chain (iptables)"
# ============================================================================

DOCKER_USER=$($SSH_TRESOR "sudo iptables -L DOCKER-USER -n -v 2>/dev/null" || echo "NOT FOUND")
if echo "$DOCKER_USER" | grep -q "DOCKER-USER"; then
  pass "DOCKER-USER chain exists"
  # Check it has restrictive rules
  if echo "$DOCKER_USER" | grep -q "192.168.0.0/24"; then
    pass "DOCKER-USER allows LAN (192.168.0.0/24)"
  else
    warn "DOCKER-USER may not have LAN allow rule"
  fi
  if echo "$DOCKER_USER" | grep -q "RETURN"; then
    pass "DOCKER-USER has RETURN (default policy works)"
  fi
else
  warn "DOCKER-USER chain not found — Docker may bypass host firewall"
fi

# ============================================================================
header "6. TRESOR — WireGuard Tunnel"
# ============================================================================

WG=$($SSH_TRESOR "sudo wg show 2>/dev/null" || echo "NOT RUNNING")
if echo "$WG" | grep -q "interface"; then
  pass "WireGuard tunnel active on Tresor"
  HANDSHAKE=$(echo "$WG" | grep "latest handshake" || echo "no handshake")
  info "Latest handshake: $HANDSHAKE"
else
  fail "WireGuard not running on Tresor"
fi

# ============================================================================
header "7. TRESOR — filebrowser-public (cloud.example.com)"
# ============================================================================

# Container running
if $SSH_TRESOR "docker ps --format '{{.Names}}' | grep -q filebrowser-public" 2>/dev/null; then
  pass "filebrowser-public container running"
else
  fail "filebrowser-public not running"
fi

# Bound to WG IP only
FB_PORTS=$($SSH_TRESOR "docker port filebrowser-public 2>/dev/null" || echo "")
if echo "$FB_PORTS" | grep -q "10\.66\.66\.2"; then
  pass "filebrowser-public bound to WG IP (10.66.66.2) only"
else
  fail "filebrowser-public binding: $FB_PORTS"
fi

# Loopback mount
CLOUD_MOUNT=$($SSH_TRESOR "findmnt /mnt/data/cloud 2>/dev/null" || echo "NOT MOUNTED")
if echo "$CLOUD_MOUNT" | grep -q "cloud.img"; then
  pass "1TB loopback mounted at /mnt/data/cloud"
  CLOUD_SIZE=$($SSH_TRESOR "df -h /mnt/data/cloud 2>/dev/null | tail -1 | awk '{print \$2}'" || echo "unknown")
  info "Cloud partition size: $CLOUD_SIZE"
else
  warn "Loopback not mounted at /mnt/data/cloud"
fi

# Data isolation — filebrowser-public should NOT see /mnt/data/files
FB_MOUNTS=$($SSH_TRESOR "docker inspect filebrowser-public --format '{{range .Mounts}}{{.Source}}→{{.Destination}} {{end}}'" 2>/dev/null || echo "")
if echo "$FB_MOUNTS" | grep -q "/mnt/data/files\|/mnt/data/media\|/mnt/hdd/data"; then
  fail "filebrowser-public can access personal data! Mounts: $FB_MOUNTS"
else
  pass "filebrowser-public data isolation OK (only sees /mnt/data/cloud)"
fi

# ============================================================================
header "8. VPS — SSH & System"
# ============================================================================

if $SSH_VPS "true" 2>/dev/null; then
  pass "VPS SSH reachable"
else
  fail "Cannot SSH to VPS — skipping VPS checks"
  # Skip to summary
  header "SUMMARY"
  echo -e "  ${GRN}PASS: $PASS${RST}  ${YEL}WARN: $WARN${RST}  ${RED}FAIL: $FAIL${RST}  ${CYN}INFO: $INFO${RST}"
  exit 1
fi

# Root login
VPS_ROOT=$($SSH_VPS "sudo sshd -T 2>/dev/null | grep -i '^permitrootlogin'" || echo "unknown")
if echo "$VPS_ROOT" | grep -qi "no"; then
  pass "VPS SSH root login disabled"
else
  fail "VPS SSH root login NOT disabled"
fi

# Password auth
VPS_PASS=$($SSH_VPS "sudo sshd -T 2>/dev/null | grep -i '^passwordauthentication'" || echo "unknown")
if echo "$VPS_PASS" | grep -qi "no"; then
  pass "VPS SSH password auth disabled"
else
  fail "VPS SSH password auth NOT disabled"
fi

# ============================================================================
header "9. VPS — UFW Firewall"
# ============================================================================

VPS_UFW=$($SSH_VPS "sudo ufw status verbose 2>/dev/null" || echo "inactive")
if echo "$VPS_UFW" | grep -q "Status: active"; then
  pass "VPS UFW active"
else
  fail "VPS UFW not active"
fi

# Check what's open
echo -e "  Open ports on VPS:"
echo "$VPS_UFW" | grep -E "ALLOW" | while read -r line; do
  info "$line"
done

# ============================================================================
header "10. VPS — nginx TLS Configuration"
# ============================================================================

# music.example.com cert
MUSIC_CERT=$($SSH_VPS "sudo test -f /etc/letsencrypt/live/music.example.com/fullchain.pem && echo exists || echo missing" 2>/dev/null)
if [[ "$MUSIC_CERT" == "exists" ]]; then
  pass "LE cert for music.example.com exists"
else
  fail "LE cert for music.example.com missing"
fi

# cloud.example.com cert
CLOUD_CERT=$($SSH_VPS "sudo test -f /etc/letsencrypt/live/cloud.example.com/fullchain.pem && echo exists || echo missing" 2>/dev/null)
if [[ "$CLOUD_CERT" == "exists" ]]; then
  pass "LE cert for cloud.example.com exists"
else
  fail "LE cert for cloud.example.com missing"
fi

# HSTS headers
MUSIC_HSTS=$($SSH_VPS "grep -c 'Strict-Transport-Security' /etc/nginx/sites-enabled/music.conf 2>/dev/null" || echo "0")
if [[ "$MUSIC_HSTS" -gt 0 ]]; then
  pass "HSTS enabled on music.example.com"
else
  warn "HSTS not found in music.conf"
fi

CLOUD_HSTS=$($SSH_VPS "grep -c 'Strict-Transport-Security' /etc/nginx/sites-enabled/cloud.conf 2>/dev/null" || echo "0")
if [[ "$CLOUD_HSTS" -gt 0 ]]; then
  pass "HSTS enabled on cloud.example.com"
else
  warn "HSTS not found in cloud.conf"
fi

# nginx server_tokens
TOKENS=$($SSH_VPS "grep -c 'server_tokens off' /etc/nginx/nginx.conf 2>/dev/null" || echo "0")
if [[ "$TOKENS" -gt 0 ]]; then
  pass "nginx server_tokens off"
else
  warn "nginx server_tokens not explicitly off"
fi

# ============================================================================
header "11. VPS — WireGuard"
# ============================================================================

VPS_WG=$($SSH_VPS "sudo wg show 2>/dev/null" || echo "NOT RUNNING")
if echo "$VPS_WG" | grep -q "interface"; then
  pass "WireGuard active on VPS"
else
  fail "WireGuard not running on VPS"
fi

# ============================================================================
header "12. VPS — Velocity (Minecraft Proxy)"
# ============================================================================

VELOCITY_STATUS=$($SSH_VPS "systemctl is-active velocity 2>/dev/null" || echo "inactive")
if [[ "$VELOCITY_STATUS" == "active" ]]; then
  pass "Velocity service running"
  # Check what it's bound to
  VEL_BIND=$($SSH_VPS "ss -tlnp | grep 25565" 2>/dev/null || echo "")
  if echo "$VEL_BIND" | grep -q "0.0.0.0:25565"; then
    info "Velocity binds 0.0.0.0:25565 (public — intentional for game server)"
  fi
else
  info "Velocity not active (may be stopped)"
fi

# ============================================================================
header "13. VPS — Listening Ports (external attack surface)"
# ============================================================================

echo -e "  All listening TCP ports on VPS public interface:"
VPS_LISTEN=$($SSH_VPS "sudo ss -tlnp | grep LISTEN" 2>/dev/null || echo "")
echo "$VPS_LISTEN" | while read -r line; do
  PORT=$(echo "$line" | awk '{print $4}')
  PROC=$(echo "$line" | grep -oP 'users:\(\("\K[^"]+' || echo "unknown")
  if echo "$PORT" | grep -q "127.0.0.1\|::1"; then
    pass "localhost only: $PORT ($PROC)"
  elif echo "$PORT" | grep -q "10.66.66"; then
    pass "WG only: $PORT ($PROC)"
  else
    case "$PORT" in
      *:22)   info "SSH: $PORT ($PROC)" ;;
      *:80)   info "HTTP: $PORT ($PROC) — redirects to HTTPS" ;;
      *:443)  info "HTTPS: $PORT ($PROC)" ;;
      *:25565) info "Minecraft: $PORT ($PROC) — public game port" ;;
      *)      warn "Unexpected open port: $PORT ($PROC)" ;;
    esac
  fi
done

# ============================================================================
header "14. EXTERNAL — Public Endpoint Probes"
# ============================================================================

# HTTPS on cloud
CLOUD_STATUS=$(curl -sI --connect-timeout 5 -o /dev/null -w "%{http_code}" "https://cloud.example.com" 2>/dev/null || echo "000")
if [[ "$CLOUD_STATUS" == "200" || "$CLOUD_STATUS" == "302" ]]; then
  pass "cloud.example.com responds over HTTPS ($CLOUD_STATUS)"
else
  warn "cloud.example.com returned $CLOUD_STATUS"
fi

# HTTP→HTTPS redirect
CLOUD_HTTP=$(curl -sI --connect-timeout 5 -o /dev/null -w "%{http_code}" "http://cloud.example.com" 2>/dev/null || echo "000")
if [[ "$CLOUD_HTTP" == "301" ]]; then
  pass "cloud.example.com HTTP→HTTPS redirect working"
else
  warn "cloud.example.com HTTP returned $CLOUD_HTTP (expected 301)"
fi

# HTTPS on music
MUSIC_STATUS=$(curl -sI --connect-timeout 5 -o /dev/null -w "%{http_code}" "https://music.example.com" 2>/dev/null || echo "000")
if [[ "$MUSIC_STATUS" == "200" || "$MUSIC_STATUS" == "302" ]]; then
  pass "music.example.com responds over HTTPS ($MUSIC_STATUS)"
else
  warn "music.example.com returned $MUSIC_STATUS"
fi

# ============================================================================
header "15. REPO — Static Analysis (Ansible configs)"
# ============================================================================

REPO="$HOME/Desktop/tresor/ansible"

# Check for plaintext secrets in non-vault files
echo -e "  Scanning for potential plaintext secrets..."
SECRETS_FOUND=$(grep -rn "password\|secret\|token\|api_key" "$REPO/inventory/group_vars/" 2>/dev/null \
  | grep -v "vault.yml" \
  | grep -v "vault_" \
  | grep -v "#" \
  | grep -v "changeme" \
  | grep -v "admin_pass.*vault" \
  | grep -v "admin_user" \
  | grep -v "htpasswd_userline" \
  | grep -v "forwarding_secret.*vault" \
  | grep -v "webhook.*vault" \
  || echo "")

if [[ -z "$SECRETS_FOUND" ]]; then
  pass "No plaintext secrets found outside vault files"
else
  warn "Potential plaintext secrets (review manually):"
  echo "$SECRETS_FOUND" | head -10 | while read -r line; do
    echo -e "    $line"
  done
fi

# host_key_checking
if grep -q "host_key_checking = False" "$REPO/ansible.cfg" 2>/dev/null; then
  warn "ansible.cfg: host_key_checking = False (MITM risk, common in homelabs)"
fi

# Broad sudo
if grep -q "NOPASSWD:ALL" "$REPO/roles/base/templates/sudoers_ansible.j2" 2>/dev/null; then
  warn "ansible user has NOPASSWD:ALL sudo (acceptable for automation, tighten later)"
fi

# VPS IP in plaintext
if grep -q "1.2.3.4" "$REPO/inventory/hosts.ini" 2>/dev/null; then
  info "VPS public IP in hosts.ini (normal, just don't push to public git)"
fi

# ============================================================================
header "SUMMARY"
# ============================================================================

echo ""
echo -e "  ${GRN}PASS: $PASS${RST}"
echo -e "  ${YEL}WARN: $WARN${RST}"
echo -e "  ${RED}FAIL: $FAIL${RST}"
echo -e "  ${CYN}INFO: $INFO${RST}"
echo ""

if [[ $FAIL -gt 0 ]]; then
  echo -e "  ${RED}Action required — review FAILs above.${RST}"
elif [[ $WARN -gt 0 ]]; then
  echo -e "  ${YEL}Mostly good — review WARNs when convenient.${RST}"
else
  echo -e "  ${GRN}All clear.${RST}"
fi

echo ""
echo -e "  Known accepted risks:"
echo -e "    • Velocity on VPS binds 0.0.0.0:25565 (public game server, by design)"
echo -e "    • velocity_allow_from is 0.0.0.0/0 in group_vars — matches intent but comment says 'restricted'"
echo -e "    • Tresor has no UFW — relies on Docker iptables (DOCKER-USER chain) + WG IP bindings"
echo -e "    • ansible user has broad NOPASSWD sudo (phase-1, tighten later)"
echo -e "    • Docker userns-remap disabled (containers use host UIDs via user: directive)"
echo ""
