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
import crypt
import traceback
import threading
import random
import string
import shutil
import csv
from imfcfg.render import TemplateLoader, init_template
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(__file__))
from typing import Any


import logging


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%d:%H:%M:%S",
)


from cachedpynetbox import pynetbox
import click

try:
    import configparser
except ImportError:
    import ConfigParser

from imfcfg.c3site import Site

site = Site()

from cachedpynetbox.nbcache.nbcache import SyncedNetbox


@click.command()
def updater():
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

    dbtruepath = os.path.join(os.path.dirname("/var/cache/imf/"), "netbox.cache-v2")
    lastfullget = 0
    while True:
        dbpath = (
            dbtruepath
            + "."
            + "".join([random.choice(string.ascii_lowercase) for i in range(0, 16)])
        )
        try:
            if time.time() - lastfullget > 900:
                sys.stderr.write(
                    "1h passed (or startup), regenerating cache from scratch\n"
                )
                lastfullget = time.time()
            elif os.path.exists(dbtruepath):
                shutil.copy2(dbtruepath, dbpath)
            nb = pynetbox(
                config.get("global", "base_uri"),
                config.get("global", "token"),
                False,
                True,
                cachetime=config.get("global", "cachetime", fallback=15.0),
                quick=True,
                dbpath=dbpath,
            )
            nb.updater()
            nb._snb._cache.db.sync()
            nb._snb._cache.db.close()
            del nb
            os.rename(dbpath, dbtruepath)
            print("refresh done")
        except:
            traceback.print_exc()
            try:
                os.unlink(dbpath)
            except:
                pass
        time.sleep(30)
