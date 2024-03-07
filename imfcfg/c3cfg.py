#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import print_function
from functools import namedtuple, reduce
import argparse
import ipaddress as ipaddr
import jinja2
import os, re, codecs, time
import requests, json
import sys
import yaml
import dbm, dbm.gnu, fcntl
import subprocess
import traceback
import threading
import random
import string
import shutil
import csv
from imfcfg.render import TemplateLoader, init_template
from pprint import pprint
from fnmatch import fnmatch
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(__file__))
from typing import Any


from imfcfg.vlans import *
from imfcfg.interfaces import *
from imfcfg.util import *
from cachedpynetbox import pynetbox
from imfcfg.nbh import *
from imfcfg.routing import *
from imfcfg.loader import *
from imfcfg.frontend import *


try:
    import configparser
except ImportError:
    import ConfigParser

from imfcfg.c3site import Site

site = Site()



class NoSuchDeviceError(Exception):
    pass


class DuplicateIfaceUnitError(Exception):
    pass


# "slug" field in netbox
ROLE_DISTRIBUTION_SWITCH = "distribution-switch"
ROLE_BORDER_ROUTER = "router"
ROLE_ACCESS_SWITCH = "access-switch"
ROLE_WIFI_ROUTER = "wifi-router"

UNUSED_IFACE_WHITELIST = re.compile(r"((xe|et|ge)-|Ethernet).*")
VLAN_IFACE_RE = re.compile(r"vlan.(\d+)")
TRANSIT_SUBIF_RE = re.compile(r"(.*)\.(\d+)")


def loadKeys(tvars):
    db_path = config.get("db", "path")
    with open(f"{db_path}/groups.yml", "r") as stream:
        groups = yaml.safe_load(stream)
        tvars.update(groups=groups)
    with open(f"{db_path}/users.yml", "r") as stream:
        users = yaml.safe_load(stream)
        tvars.update(users=users)
    with open(f"{db_path}/keys.yml", "r") as stream:
        keys = yaml.safe_load(stream)
        tvars.update(keys=keys)
    with open(f"{db_path}/event-config.json", "r") as stream:
        event_config = json.load(stream)
        event_config["md5crypt_admin_password"] = hash_password(
            event_config["admin_password"], "md5"
        )
        event_config["crypted_admin_password"] = hash_password(
            event_config["admin_password"], "sha256"
        )
        tvars.update(event_config=event_config)
    with open(f"{db_path}/access-users.json", "r") as stream:
        access_users = json.load(stream)
        tvars.update(access_users=access_users)


dbpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "netbox.cache-v2")


def loadVars(device=None, tplname=None, loader=None):
    tvars = {}

    if tplname is None:
        tplname = device

    typ, data, path, checkmodif = loader.get_source_type(templateEnv, tplname)

    # load ssh keys
    loadKeys(tvars)

    # load router/switch specific data
    if typ == "router":
        loadRouterData(tvars, device)

        routers = nb.dev_by_role(ROLE_BORDER_ROUTER)
        tvars.update(iBGP4=iBGP4(device, routers))
        tvars.update(iBGP6=iBGP6(device, routers))
    if typ == "switch":
        loadSwitchData(tvars, device)

    tvars.update(vlans=loadVlans())

    tvars.update(prefixes=loadPrefixes())

    return tplname, tvars


if __name__ == "__main__":
    # load config
    global nb
    cfg_defaults = {
        "base_uri": "https://localhost:443/api/",
        "token": "None",
        "username": "None",
        "password": "None",
    }

    if "ConfigParser" in sys.modules.keys():
        config = ConfigParser.ConfigParser(cfg_defaults)
    else:
        config = configparser.ConfigParser(cfg_defaults)

    try:
        config.read(os.path.expanduser("~/.netboxrc"))
    except OSError:
        sys.stderr.write("%s file could not be opened, does it exist?" % userrcfile)
        sys.exit(1)

    # parse arguments
    parser = argparse.ArgumentParser(prog="C3NOC config generator")
    parser.add_argument("-t", dest="template", type=str, help="the template to fill")
    parser.add_argument(
        "-r",
        dest="router",
        type=str,
        help="router for which additional template variables should be loaded",
    )
    parser.add_argument(
        "-s",
        dest="switch",
        type=str,
        help="switch for which additional template variables should be loaded",
    )
    parser.add_argument(
        "-o",
        dest="output",
        type=argparse.FileType("w"),
        default=sys.stdout,
        help="output file (default: stdout)",
    )
    parser.add_argument(
        "-D", dest="outdir", type=str, help="output directory for multi-device mode"
    )
    parser.add_argument(
        "-d", dest="daemon", action="store_const", const=True, help="run HTTP server"
    )
    parser.add_argument(
        "-O", dest="offline", action="store_const", const=True, help="no IPAM access"
    )
    parser.add_argument(
        "--vars",
        dest="vars",
        action="store_const",
        const=True,
        help="show template variables",
    )
    parser.add_argument(
        "--json",
        dest="json",
        action="store_const",
        const=True,
        help="show template variables in JSON",
    )
    parser.add_argument(
        "--trace",
        dest="trace",
        action="store_const",
        const=True,
        help="show IPAM requests with latency",
    )
    parser.add_argument(
        "--interactive",
        dest="interactive",
        action="store_const",
        const=True,
        help="start python shell with vars available",
    )
    args = parser.parse_args()

    if args.trace:
        import logging

        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s.%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d:%H:%M:%S",
        )

    nb = pynetbox(
        config.get("global", "base_uri"),
        config.get("global", "token"),
        (config.get("global", "username"), config.get("global", "password")),
        args.offline,
        args.trace,
        cachetime=config.get("global", "cachetime", fallback=15.0),
        readonly=args.daemon,
        dbpath=dbpath,
    )
    store_nb(nb)

    loader, templateEnv = init_template(
        nb, os.path.expanduser(config.get("templates", "path"))
    )

    if args.router:
        TemplateLoader.default_role = "router"
    elif args.switch:
        TemplateLoader.default_role = "switch"

    if args.template is not None:
        template_file, locVars = loadVars(
            args.router or args.switch, tplname=args.template, loader=loader
        )
    elif args.router or args.switch:
        devname = args.router or args.switch
        if "?" in devname or "*" in devname:
            outdir = args.outdir or "."
            devices = nb.devices()
            for device in devices:
                if not fnmatch(device["name"], devname):
                    continue
                if device["device_role"]["slug"] not in ["access-switch", "router"]:
                    continue
                name = device["name"]
                sys.stderr.write("writing %s.conf\n" % (name))
                try:
                    template_file, locVars = loadVars(name, loader=loader)
                    tpl = templateEnv.get_template(template_file)
                    with open(os.path.join(outdir, "%s.conf" % (name)), "w") as fd:
                        print(tpl.render(**locVars), file=fd)
                except:
                    sys.stderr.write("error while rendering %s.conf:\n" % (name,))
                    traceback.print_exc()
            sys.exit(0)
        template_file, locVars = loadVars(devname, loader=loader)
    else:
        sys.stderr.write("need template (-t), router (-r) or switch (-s)\n")
        sys.exit(1)

    if args.json:
        sys.stdout.write(json.dumps(to_dict(locVars), indent=4, sort_keys=True))
        sys.exit(0)

    if args.vars:
        pprint(locVars)
        sys.exit(0)

    if args.interactive:
        print(", ".join(locVars.keys()))

        import code

        shellvars = {}
        shellvars.update(globals())
        shellvars.update(locals())
        shellvars.update(locVars)
        code.interact(local=shellvars)
        sys.exit(0)

    tpl = templateEnv.get_template(template_file)
    print(tpl.render(**locVars), file=args.output)
