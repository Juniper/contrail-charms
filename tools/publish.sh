#!/bin/bash -ex

my_file="$(readlink -e "$0")"
my_dir="$(dirname $my_file)"

"$my_dir/generate-repo-info.sh"

charm login
team="juniper-os-software"
for folder in contrail-agent contrail-analytics contrail-analyticsdb contrail-controller contrail-keystone-auth contrail-openstack contrail-kubernetes-master contrail-kubernetes-node ; do
  id="~$team/$folder"
  res=`charm push "$my_dir/../$folder" cs:${id}`
  echo "$res"
  num=`echo "$res" | grep "cs:${id}" | sed "s|^.*cs:${id}-\([0-9]*\).*$|\1|"`
  charm release cs:${id}-$num
  charm grant "${id}" --channel stable --acl read --set everyone
  charm set "${id}" bugs-url="https://github.com/Juniper/contrail-charms/issues" homepage="https://github.com/Juniper/contrail-charms"
done
