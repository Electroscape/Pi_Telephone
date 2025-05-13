#!/bin/bash
# shellcheck disable=SC2164
python3 -m venv venv
source venv/bin/activate
bash install_depencies.sh
pip3 install -r requirements.txt
