#!/usr/bin/env python

import subprocess, os, sys, random, time, re, syslog, hashlib, socket
if sys.version_info[0] < 3:
    # legacy python2 T_T
    from six.moves import urllib
    PY3 = False
else:
    import urllib.request, urllib.parse, urllib.error
    PY2 = True

# Parameters
interval = float(sys.argv[1])
target = sys.argv[2]
STATUS_HOST = "https://example.org/snafu/%s/%s?%s"
hostname = os.uname()[1]

# error reporting stuff
def report_status(code, reason=None, errorlog=None):
    params = {}
    if reason is not None:
        params['reason'] = reason
    params = urllib.parse.urlencode(params)
    url = STATUS_HOST % (hostname, code, params)
    if errorlog is not None:
        if PY3:
            req = urllib.request.Request(url=url, data=errorlog,method='POST')
        else:
            req = urllib.request.Request(url=url, data=errorlog)
            req.get_method = lambda: 'POST'
    else:
        req = urllib.request.Request(url=url)
    try:
        f = urllib.request.urlopen(req)
        ret = f.read() == b'OK'
        f.close()
        return ret
    except urllib.error.URLError:
        return False

def autodeploy_active():
    " check if auto deploy is active "
    url = STATUS_HOST % (hostname, "deployactive", "")
    req = urllib.request.Request(url=url)
    try:
        f = urllib.request.urlopen(req)
        ret = f.read().decode(errors='replace').strip() == "yes"
        f.close()
        return ret
    except urllib.error.URLError:
        return False


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

csumfiles = ["autoreload.py", "autoreload.sh", "autoreload_legacy.sh", "artnet-bridge.sh"]
csums = []
for fn in csumfiles:
    if not os.path.isfile(fn):
        continue
    try:
        csum = hashlib.sha1(file(fn, "rb").read()).hexdigest()
        csums.append("%s:%s" % (fn, csum[:8]))
    except:
        csums.append("%s:ERROR" % (fn,))
syslog.syslog(syslog.LOG_ERR, "file csums: " + ", ".join(csums))

while True:
    if not autodeploy_active():
        time.sleep(random.normalvariate(interval, interval * 0.1))
        continue

    try:
        report_status('fetchedconfig')
        subprocess.check_output(
            [
                "FastCli",
                "-p",
                "15",
                "-c",
                "configure replace https://deploy.c3noc.net/%s" % (os.uname()[1],),
            ]
        )
    except subprocess.CalledProcessError as e:
        print(e.output)
        syslog.syslog(syslog.LOG_ERR, "reload error: %r" % (e,))
        sys.stderr.write("reload error: %r\n" % (e,))
        report_status('failure', reason='applyfail', errorlog=e.output)
        
        time.sleep(random.normalvariate(90.0, 15.0))
        continue

    time.sleep(3.0)
    try:
        subprocess.check_call(["ping", "-i1", "-w3", "-c3", target])
        #sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        #metric = "config_reloaded.%s:1|c" % os.uname()[1]
        #sock.sendto(str.encode(metric), ("autodeploy_stats", 9125))
        report_status('success', reason='applied')
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
        report_status('failure', reason='connectivity')
        time.sleep(random.normalvariate(90.0, 15.0))

    subprocess.check_call(["FastCli", "-p", "15", "-c", "write mem"])
    report_status('success', reason='persisted')
    time.sleep(random.normalvariate(interval, interval * 0.1))
