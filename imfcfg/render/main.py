import jinja2
import os
import re
import codecs
from imfcfg.util import *


def init_template(nb, path=None):
    loader = TemplateLoader(nb, path)
    templateEnv = jinja2.Environment(
        loader=loader, trim_blocks=True, lstrip_blocks=True
    )
    templateEnv.filters.update(nethost=nethost)
    templateEnv.filters.update(sortifnames=sortifnames)
    templateEnv.filters.update(vlanjoin=vlanjoin)
    templateEnv.globals.update(nin=nin)
    templateEnv.globals.update(net2ip=net2ip)
    templateEnv.globals.update(nethost=nethost)
    templateEnv.globals.update(max=max)
    templateEnv.globals.update(is_junos_els=is_junos_els)
    templateEnv.globals.update(get_mgmt_vlan=get_mgmt_vlan)
    templateEnv.globals.update(is_junos_ssh_outdated=is_junos_ssh_outdated)
    templateEnv.globals.update(split_multiline=split_multiline)
    templateEnv.globals.update(regex_match=regex_match)
    templateEnv.globals.update(hash_password=hash_password)
    return loader, templateEnv


class TemplateLoader(jinja2.BaseLoader):
    target_re = re.compile(
        "\{#\s*c3cfg:\s*(?P<type>router|switch)\s+(?P<rules>.*)\s+#\}"
    )
    default_role = "router"
    nb = None

    def __init__(self, nb, path=None):
        self.nb = nb
        if not path:
            self.path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "../templates"
            )
        else:
            self.path = path

    def get_source_type(self, environment, name):
        from jinja2.exceptions import TemplateNotFound

        # loading templates by explicit filename
        for lname in [name, name + ".j2"]:
            directpath = os.path.join(self.path, lname)
            if os.path.exists(directpath):
                with codecs.open(directpath, "r", "UTF-8") as f:
                    mtime = os.path.getmtime(directpath)
                    return (
                        self.default_role,
                        f.read(),
                        directpath,
                        lambda: mtime == os.path.getmtime(directpath),
                    )

        device = (
            self.nb.dev_by_serial(name)
            if len(device := self.nb.dev_by_name(name)) == 0
            else device
        )
        if len(device) == 0:
            raise NoSuchDeviceError('Device "%s" does not exist!' % name)
        if len(device) != 1:
            raise ValueError(
                'Found more than one device for "%s" for some reason' % name
            )
        device = device[0]

        # search templates using:
        #   {# c3cfg: (router|switch) <name> [important] #}
        candidates = []
        important = False
        mtimedir = os.path.getmtime(self.path)

        for tpl in os.listdir(self.path):
            if tpl.startswith(".") or not tpl.endswith(".j2"):
                continue
            with codecs.open(os.path.join(self.path, tpl), "r", "UTF-8") as f:
                data = f.read()
            for match in self.target_re.finditer(data):
                rules = match.group("rules").split(" ")
                matched = True
                this_imp = False
                # process the rules
                while len(rules) > 0:
                    rule = rules.pop(0)
                    match_val = name
                    if rule in ["device_type", "device_role"]:
                        match_val = device[rule]["slug"]
                        if len(rules) < 1:
                            sys.stderr.write(
                                "Template %s has invalid c3cfg (rules too short)\n"
                                % tpl
                            )
                            matched = False
                            break
                        regex = rules.pop(0)
                    elif rule == "important":
                        this_imp = True
                        continue
                    else:
                        regex = rule
                    if re.match(regex, match_val) is None:
                        matched = False
                        break
                if not matched:
                    continue
                if important and (not this_imp):
                    continue
                if this_imp:
                    important = True
                    candidates = []
                candidates.append(
                    (
                        os.path.join(self.path, tpl),
                        match.group("rules"),
                        data,
                        match.group("type"),
                    )
                )
                break

        if len(candidates) == 0:
            raise TemplateNotFound('no template matches host name "%s"' % (name))
        if len(candidates) > 1:
            raise TemplateNotFound(
                'multiple templates match host name "%s":\n\t%s'
                % (
                    name,
                    "\n\t".join(["%s [%s]" % (tpl[0], tpl[1]) for tpl in candidates]),
                )
            )

        # directory mtime will pick up creation/deletion of files, but modifications
        # of other files' regexes will go unnoticed... :/
        path, rules, data, typ = candidates[0]
        mtime = os.path.getmtime(path)

        def checkmodif():
            return mtime == os.path.getmtime(path) and mtimedir == os.path.getmtime(
                self.path
            )

        return typ, data, path, checkmodif

    def get_source(self, *args, **kwargs):
        return tuple(self.get_source_type(*args, **kwargs)[1:])
