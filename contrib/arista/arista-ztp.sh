#!/bin/bash
SERIAL=$(echo show version|FastCli -p2|grep Serial|awk '{print $3}')
FastCli -p2 <<EOF
enable
copy http://203.0.113.1:8069/by-serial/${SERIAL} flash:startup-config
EOF

SUCCESS="$(echo -e "enable\nshow startup-config"|FastCli -p2|wc -l)"
if [ "$SUCCESS" != "0" ];then
	(
	echo enable
	echo config
	echo boot system flash:EOS.swi
	)|FastCli -p2
else
	exit 2
fi
