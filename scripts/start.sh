#!/bin/bash

cd /home/kmx/download_bot

pip install -r requirements.txt --break-system-packages
python3 main.py --prod --log-file main.log
