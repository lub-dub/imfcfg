#!/bin/sh

config_url="http://deploy.example.org/$(hostname)"
status_url="http://deploy.example.org/snafu/$(hostname)"
config_file=/tmp/autoreload.config
load_file=/tmp/autoreload.load
check_file=/tmp/autoreload.check
committed_file=/tmp/autoreload.committed
ping_target="203.0.113.1"
rand="$(dd if=/dev/urandom bs=1 count=64 status=none | base64 | grep -zo "[0-9]" | tail -n 2 | /bin/sh -c 'while read N ; do echo -n "$N" ; done')"

# check if we should uninstall ourselves
# if there is an AUTODEPLOY:<EVENT> annotation on the host-name we should be running
if ! echo "show configuration system host-name" | /usr/sbin/cli | grep -q "AUTODEPLOY:"; then
echo "autoreload unwanted, uninstalling..."
fetch -q -o /dev/null "$status_url/uninstall"
echo "y" | crontab -r
rm /var/tmp/autoreload.*
exit 99
fi

# check if we should currently do updates at all
if ! fetch -q -o - "$status_url/deployactive" | grep -q yes; then
echo "autoreoad inactive, exiting"
exit 10
fi

sleep $rand

# abort if we can not fetch a config
fetch -o $config_file $config_url || exit 1
fetch -q -o /dev/null "$status_url/fetchedconfig"
chmod 644 $config_file

# check if config has changed
touch $committed_file
if diff -q $committed_file $config_file; then
fetch -q -o /dev/null "$status_url/success?reason=noop"
exit 0
fi

# check if the config has errors
{ echo "configure"
  echo "load override $config_file | save $load_file"
  echo "commit check | save $check_file"
  echo "rollback 0"
  echo "exit"
} | /usr/sbin/cli

if grep -q error $load_file; then
fetch -q -o /dev/null "$status_url/failure?reason=load"
curl -s --data-binary "@$load_file" "$status_url/failure?reason=load"
rm $load_file
exit 2
fi

if grep -q error $check_file; then
fetch -q -o /dev/null "$status_url/failure?reason=check"
curl -s --data-binary "@$check_file" "$status_url/failure?reason=check"
rm $check_file
exit 3
fi

# sanity checks done, we can try to apply it
{ echo "configure"
  echo "load override $config_file | match IDONOTWANTYOUROUTPUT"
  echo "commit confirmed 2 and-quit"
} | /usr/sbin/cli

/bin/sleep 30

if /sbin/ping -c 3 $ping_target; then
{ echo "configure"
  echo "commit check and-quit"
} | /usr/sbin/cli
fetch -q -o /dev/null "$status_url/success"
cp $config_file $committed_file
exit 0
fi

/bin/sleep 150

# if we rolled back maybe we can post this general failure state still...
fetch -q -o /dev/null "$status_url/failure"
