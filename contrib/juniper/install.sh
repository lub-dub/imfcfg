#!/bin/bash

cd $(dirname $0)


ping -c1 -w1 $1 || {
    printf "\e[31;1m%s seems to be unreachable?\e[m\n" $1 >&2
    exit 1
}

password="$(jq -r .admin_password < ../db/event-config.json)"

scp -O -o 'BatchMode yes' -o 'StrictHostKeyChecking no' autoreload.* $1:/var/tmp/

expect <<EOD
spawn ssh -oStrictHostKeyChecking=no $1
expect "> "
send "start shell user root\n"
expect "Password:"
send "${password}\n"
expect ":RE:0% "
send "crontab /var/tmp/autoreload.cron\n"
expect ":RE:0% "
send "crontab -l\n"
expect ":RE:0% "
EOD
