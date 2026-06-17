#!/usr/bin/env bash
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -q tmux
echo "tmux installé : $(tmux -V)"
