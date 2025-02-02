#!/bin/bash

cd $BOT_DIR/

pip install -r requirements.txt --break-system-packages
python3 main.py --prod --log-file main.log
