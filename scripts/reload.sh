#!/bin/bash

echo "sleep 2; echo $PASSWORD | sudo -S systemctl restart bot" | at now
