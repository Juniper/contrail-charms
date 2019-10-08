#!/bin/bash
# The script is needed to support Python2 and Python3.
# Returns the sys.path in the correct Python version for the component.

component=$1
import_component="import os,sys; sys.stderr=open(os.devnull,'wb'); import $component"
get_path="import sys; paths=[p for p in sys.path if 'dist-packages' in p and '.local' not in p]; print(paths[-1])"
python -c "$import_component" &>/dev/null
if [ $? -ne 0 ]; then
  python3 -c "$import_component" &>/dev/null
  sys_path=`python3 -c "$get_path"`
else
  sys_path=`python -c "$get_path"`
fi
echo $sys_path | tr -d '\n'
