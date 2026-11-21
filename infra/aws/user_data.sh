#!/usr/bin/env bash
# First-boot bootstrap (root). Docker + compose, swap as a safety net, unattended
# security updates. No SSH hardening needed: the SG has no port 22 (SSM only).
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update && apt-get upgrade -y && apt-get autoremove -y
apt-get install -y ca-certificates curl gnupg unattended-upgrades

# 2 GB swap: absorbs spikes; never the plan for steady-state memory.
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=10
  echo 'vm.swappiness=10' >> /etc/sysctl.conf
fi

# Docker + compose plugin
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# AWS CLI v2 (not in apt on 24.04): needed for `aws ecr get-login-password` at deploy.
snap install aws-cli --classic
usermod -aG docker ubuntu

# Cap container log growth (the old droplet's disk/logs were a pain point).
cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
JSON
systemctl restart docker

# App directory
mkdir -p /opt/plynth
chown ubuntu:ubuntu /opt/plynth

echo "user_data bootstrap complete" > /var/log/plynth-bootstrap.done
