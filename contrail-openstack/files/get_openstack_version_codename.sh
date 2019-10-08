#!/bin/bash
# The script is needed to support Python2 and Python3.
# Returns running version of OpenStack component.

dist=$1
py_get_version="import os,pkg_resources,sys; sys.stderr=open(os.devnull,'wb'); version=pkg_resources.get_distribution('$dist').version; print(version)"
version=`python -c "$py_get_version"`
if [ $? -ne 0 ]; then
  version=`python3 -c "$py_get_version"`
fi
echo $version |  tr -d '\n'
