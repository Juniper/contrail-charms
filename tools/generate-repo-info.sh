#!/bin/bash -e

my_file="$(readlink -e "$0")"
my_dir="$(dirname $my_file)"

function write_repo_info() {
  local folder=$1
  printf "commit-sha-1: $(git rev-parse HEAD)\ncommit-short: $(git rev-parse --short HEAD)\nbranch: $(git rev-parse --abbrev-ref HEAD)\nremote: $(git config --get remote.origin.url)\ninfo-generated: $(date -u)" > "$my_dir/../$folder/repo-info"
}

for folder in contrail-agent contrail-analytics contrail-analyticsdb contrail-controller contrail-keystone-auth contrail-openstack ; do
  write_repo_info $folder
done
