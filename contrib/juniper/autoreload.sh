#!/bin/sh

sys_host=$(hostname)
config_url=http://deploy.c3noc.net/"$sys_host"
ping_target="203.0.113.1"
rand=${rand:-"$(dd 2>/dev/null if=/dev/urandom bs=1 count=64 | base64 | grep -zo "[0-9]" | sed -E 's/(..).*/\1/' | sed 1q)"} # 0-99 weird distribution

sleep $rand

run=/var/jail/run

while true; do
	curl -s $config_url-o "$run"/imfcfg.conf.new

	[ -e "$run"/imfcfg.conf ] || touch "$run"/imfcfg.conf
	diff "$run"/imfcfg.conf.new "$run"/imfcfg.conf >/dev/null
	if [ $? -ne 1 ]; then
		exit
	fi
	conf_host=$(sed -n -E 's/ *host-name +(SW.*);/\1/p' $run/imfcfg.conf.new)
	if [ "$sys_host" != "$conf_host" ]; then
		echo "[$(date)] Host mismatch $sys_host $conf_host" \
		     >> $run/imfcfg-autoreload.log
		sleep $rand
		continue
	fi

	mv $run/imfcfg.conf.new $run/imfcfg.conf
	break
done

{ echo "configure"
  echo "load override $run/imfcfg.conf"
  echo "commit confirmed 2 and-quit"
} | /usr/sbin/cli

/bin/sleep 30

/sbin/ping -c 3 "$ping_target" && {
 echo "configure"
 echo "commit check and-quit"
} | /usr/sbin/cli

date > $run/imfcfg-autoreload-last-change
