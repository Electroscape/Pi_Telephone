#!/bin/bash
# shellcheck disable=SC2164

# Make sure dir is inside Pi_Telephone folder
cd "${0%/*}"

# Copy local sound files of the telephone
SRC="../Pi_Telephone_files"
DEST="./Pi_Telephone_files"

if [ -d "$DEST" ]; then
    echo "Destination folder already exists. Skipping copy."
else
    cp -r "$SRC" "$DEST"
    echo "Folder copied successfully."
fi

python3 -m venv venv
source venv/bin/activate
bash install_depencies.sh
pip3 install -r requirements.txt
