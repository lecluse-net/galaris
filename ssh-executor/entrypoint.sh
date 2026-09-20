#!/bin/sh
set -eu

umask 077
mkdir -p \
    /data/ssh-executor/home \
    /data/ssh-executor/run \
    /data/ssh-executor/state/authorized_keys \
    /data/ssh-executor/state/host_keys
chmod 0755 /data /data/ssh-executor /data/ssh-executor/home
chown 0:19999 /data/ssh-executor/run
chmod 0770 /data/ssh-executor/run
chmod 0700 /data/ssh-executor/state
exec /usr/bin/tini -g -- python3 /opt/galaris-executor/executord.py serve
