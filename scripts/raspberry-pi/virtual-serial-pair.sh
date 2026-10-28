#!/usr/bin/env bash
# Bench test without hardware: creates two linked virtual serial ports.
# Use /tmp/ttyV0 as the Sender port and /tmp/ttyV1 as the Receiver port.
sudo apt-get install -y socat >/dev/null
exec socat -d -d pty,raw,echo=0,link=/tmp/ttyV0 pty,raw,echo=0,link=/tmp/ttyV1
