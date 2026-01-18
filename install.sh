#!/bin/bash
# shellcheck disable=SC2164

sudo apt install libopenblas-dev sshpass libasound2-dev python3-dev -y

python3 -m venv venv
source venv/bin/activate
bash install_depencies.sh
pip3 install -r requirements.txt


## First run ssh to pi_music once so it can store the ssh-key
#sshpass -pPASSWORD_ESCAPE ssh user@pi_ip_address