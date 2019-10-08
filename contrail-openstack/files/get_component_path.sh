#!/bin/bash
# The script is needed to support Python2 and Python3.
# Returns path to component in correct Python version.

component=$1
py_get_component="import os,$component; component_path = os.path.dirname($component.__file__); print(component_path)"
component_path=`python -c "$py_get_component"`
if [ $? -ne 0 ]; then
  component_path=`python3 -c "$py_get_component"`
fi
echo $component_path |  tr -d '\n'
