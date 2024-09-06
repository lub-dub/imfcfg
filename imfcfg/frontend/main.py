from flask import Flask, g, current_app, Response, redirect
from imfcfg.c3cfg import loadVars, loadKeys
import os
import yaml
import json
from copy import deepcopy
from imfcfg.nbh import *
from imfcfg.loader import *
from imfcfg.routing import *
from imfcfg.render import init_template, TemplateLoader
from imfcfg.util import hash_password

try:
    import configparser
except ImportError:
    import ConfigParser


class NoSuchDeviceError(Exception):
    pass


def get_nb():
    if nb not in g:
        g.nb = get_nb()
    return db


def create_app(nb=None):

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

    dbtruepath = os.path.join("/var/cache/imf/", "netbox.cache-v2")
    nb = pynetbox(
        config.get("global", "base_uri"),
        config.get("global", "token"),
        False,
        False,
        cachetime=config.get("global", "cachetime", fallback=15.0),
        readonly=True,
        dbpath=dbtruepath,
        quick="semi",
    )

    store_nb(nb)
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    app.jinja_loader = lambda x: TemplateLoader(nb, x)
    app.config.nb = nb
    app.config.loader, app.config.templateEnv = init_template(
        nb, os.path.expanduser(config.get("templates", "path"))
    )

    tvars = {}
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
            event_config["admin_password"], "sha256"
        )
        event_config["md5crypt_admin_password"] = hash_password(
            event_config["admin_password"], "md5"
        )
        tvars.update(event_config=event_config)
    with open(f"{db_path}/access-users.json", "r") as stream:
        access_users = json.load(stream)
        tvars.update(access_users=access_users)

    app.config.tvars = tvars

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    @app.route("/status")
    def status():
        return "It works"

    @app.route("/<device>")
    def render_hostname(device):
        tvars = deepcopy(current_app.config.tvars)
        try:
            typ, data, path, checkmodif = current_app.config.loader.get_source_type(
                current_app.config.templateEnv, device
            )
            if typ == "router":
                loadRouterData(tvars, device)

                routers = nb.dev_by_role(ROLE_BORDER_ROUTER)
                tvars.update(iBGP4=iBGP4(device, routers))
                tvars.update(iBGP6=iBGP6(device, routers))
            if typ == "switch":
                loadSwitchData(tvars, device)
            tvars.update(vlans=loadVlans())

            tvars.update(prefixes=loadPrefixes())
        except NoSuchDeviceError as e:
            return "Hostname not found", 404

        tpl = current_app.config.templateEnv.get_template(device)
        dev_config = tpl.render(**tvars)
        rsp = Response(dev_config, content_type="text/plain")
        return rsp

    @app.route("/by_serial/<serial>")
    def render_serial(serial):
        device = nb.dev_by_serial(serial)
        if len(device) == 0:
            return "Serial not found", 404
        name = device[0]["name"]
        return redirect(f"/{name}")

    return app
