#!/bin/sh

config_url="http://deploy.c3noc.net/$(hostname)"
ping_target="203.0.113.1"
rand="$(dd if=/dev/urandom bs=1 count=64 | base64 | grep -zo "[0-9]" | tail -n 2 | /bin/sh -c 'while read N ; do echo -n "$N" ; done')"

sleep $rand

{ echo "configure"
  echo "load override $config_url"
  echo "commit confirmed 2 and-quit"
} | /usr/sbin/cli

/bin/sleep 30

/sbin/ping -c 3 $ping_target && {
 echo "configure"
 echo "commit check and-quit"
} | /usr/sbin/cli
