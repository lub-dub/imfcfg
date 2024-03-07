import ipaddress as ipaddr

import sys

from c3site import Site

site = Site()


class Vlan(object):
    @staticmethod
    def create(v, nbprefixes):
        vid = v["vid"]
        if vid >= site.l2vlan:
            return {vid: L2Vlan(vid, v)}
        return {vid: L3Vlan(vid, v, nbprefixes)}

    def __init__(self, vid, v):
        self.vid = vid
        self.vid_name = "V%d" % vid
        self.name = v["name"]
        self.tags = v["tags"]
        self.irbloc = []
        self.prefix4 = None
        self.prefix6 = None
        self.layer3 = False
        self.group = (v.get("group") or {}).get("slug")

    def __repr__(self):
        return "<%s: vid=%d>" % (self.__class__.__name__, self.vid)

    def __cmp__(self, other):
        return cmp(self.vid, other.vid)

    def __lt__(self, other):
        return self.vid < other.vid

    def __eq__(self, other):
        return self.vid == other.vid

    def to_dict(self):
        return {
            "vid": self.vid,
            "name": self.name,
            "tags": list(self.tags),
            "prefix4": str(self.prefix4["prefix"]) if self.prefix4 else None,
            "prefix6": str(self.prefix6["prefix"]) if self.prefix6 else None,
            "is_layer3": self.layer3,
            "sitewide": getattr(self, "sitewide", None) or False,
        }


class L2Vlan(Vlan):
    def __init__(self, vid, v):
        super(L2Vlan, self).__init__(vid, v)
        self.sitewide = True


class L3Vlan(Vlan):
    def __init__(self, vid, v, prefixes):
        super(L3Vlan, self).__init__(vid, v)
        self.sitewide = False
        if self.vid not in prefixes:
            sys.stderr.write("vlan %r has no prefix!\n" % (self.vid))
            self.prefixes = []
        else:
            self.prefixes = prefixes[self.vid]

        if len(self.allprefix4()) == 1:
            self.prefix4 = self.allprefix4()[0]

        if len(self.allprefix6()) == 1:
            self.prefix6 = self.allprefix6()[0]
        elif len(self.allprefix6()) == 0 and self.vid < site.l2vlan:
            self.prefix6 = {
                "prefix": ipaddr.ip_network(site.pfx6 % self.vid),
                "name": "default-v6",
                "firewall": "public",
            }
            if self.prefix4:
                self.prefix6["firewall"] = self.prefix4["firewall"]

        self.layer3 = bool(self.prefix4 or self.prefix6)

    def allprefix4(self):
        return [pfx for pfx in self.prefixes if pfx["prefix"].version == 4]

    def allprefix6(self):
        return [pfx for pfx in self.prefixes if pfx["prefix"].version == 6]


class VlanDict(dict):
    def __init__(self, netbox, prefixnew):
        super(VlanDict, self).__init__()
        self._nb = netbox
        for v in self._nb.vlans():
            self.update(Vlan.create(v, prefixnew))
            vid = v["vid"]
