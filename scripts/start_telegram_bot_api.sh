#!/bin/bash

cd $BOT_DIR/
$TELEGRAM_BOT_API_BIN \
    --local \
    --http-port 8001 \
    --api-id $TELEGRAM_API_ID \
    --api-hash $TELEGRAM_API_HASH \
    --dir $BOT_DIR/.telegram_bot_api_data \
    --log $LOG_DIR/telegram_bot_api.log
