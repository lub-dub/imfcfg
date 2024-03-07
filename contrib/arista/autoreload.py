#!/usr/bin/env python

import subprocess, os, sys, random, time, re, syslog, hashlib, socket

interval = float(sys.argv[1])
target = sys.argv[2]

pid = os.fork()
if pid != 0:
    sys.exit(0)
os.setsid()
os.chdir("/mnt/flash")

with open("/dev/null", "w+") as fd:
    os.dup2(fd.fileno(), 0)
with open("/mnt/flash/autoreload.log", "a") as fd:
    os.dup2(fd.fileno(), 1)
    os.dup2(fd.fileno(), 2)

syslog.openlog("autoreload.py", 0, syslog.LOG_LOCAL4)

csumfiles = ["autoreload.py", "autoreload.sh", "artnet-bridge.sh"]
csums = []
for fn in csumfiles:
    try:
        csum = hashlib.sha1(file(fn, "rb").read()).hexdigest()
        csums.append("%s:%s" % (fn, csum[:8]))
    except:
        csums.append("%s:ERROR" % (fn,))
syslog.syslog(syslog.LOG_ERR, "file csums: " + ", ".join(csums))

while True:
    try:
        subprocess.check_call(
            [
                "FastCli",
                "-p",
                "15",
                "-c",
                "configure replace https://deploy.c3noc.net/%s" % (os.uname()[1],),
            ]
        )
    except subprocess.CalledProcessError as e:
        syslog.syslog(syslog.LOG_ERR, "reload error: %r" % (e,))
        sys.stderr.write("reload error: %r\n" % (e,))

        time.sleep(random.normalvariate(90.0, 15.0))
        continue

    time.sleep(3.0)
    try:
        subprocess.check_call(["ping", "-i1", "-w3", "-c3", target])
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        metric = "config_reloaded.%s:1|c" % os.uname()[1]
        sock.sendto(str.encode(metric), ("autodeploy_stats", 9125))
    except subprocess.CalledProcessError as e:
        sys.stderr.write("connectivity problem: %r\n" % (e,))
        subprocess.check_call(
            ["FastCli", "-p", "15", "-c", "copy startup-config running-config"]
        )

        time.sleep(3.0)
        syslog.syslog(
            syslog.LOG_ERR,
            "connectivity problem after autoreload, reverted to startup config!",
        )

        time.sleep(random.normalvariate(90.0, 15.0))

    subprocess.check_call(["FastCli", "-p", "15", "-c", "write mem"])
    time.sleep(random.normalvariate(interval, interval * 0.1))
