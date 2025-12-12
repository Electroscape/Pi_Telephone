#!/bin/bash
# shellcheck disable=SC2164

sudo apt-get install libopenblas-dev
 
python3 -m venv venv
source venv/bin/activate
bash install_depencies.sh
pip3 install -r requirements.txt
