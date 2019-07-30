#!/bin/bash -ex

my_file="$(readlink -e "$0")"
my_dir="$(dirname $my_file)"

bundle="$1"
if [ ! -f "$my_dir/../examples/$bundle/bundle.yaml" ]; then
  echo "ERROR: There is no bundle.yaml file at path $my_dir/../examples/$bundle/bundle.yaml"
  exit 1
fi

charm login
team="juniper-os-software"
id="~$team/bundle/$bundle"

res=`charm push "$my_dir/../examples/$bundle" cs:${id}`
echo "$res"
num=`echo "$res" | grep "cs:${id}" | sed "s|^.*cs:${id}-\([0-9]*\).*$|\1|"`
charm release cs:${id}-$num
charm grant "${id}" --channel stable --acl read --set everyone
charm set "${id}" bugs-url="https://github.com/Juniper/contrail-charms/issues" homepage="https://github.com/Juniper/contrail-charms"
