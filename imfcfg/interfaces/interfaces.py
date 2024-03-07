from util import *


class Iface(object):
    def __init__(self, this, iface, remote):
        self._this = this
        self._iface = iface
        self._remote = remote
        self.other = remote
        lag = (iface.get("lag") or {}).get("name")
        self.ifname = lag or iface.get("name")
        self.tags = get_tags(iface)
        self.mclag = iface["custom_fields"].get("mclag", False)
        self.ptp_upstream = iface["custom_fields"].get("ptp_upstream", False)
        self.speed = iface["type"]["value"]
        self.speed_override = iface["speed"]
        self.is_lag_master = iface["type"]["value"] == "lag"
        self.is_virtual = iface["type"]["value"] == "virtual"
        self.is_dataplane = (not self.is_virtual) and not (iface["mgmt_only"])

    def get_speed(self):
        if self.speed_override is not None:
            if self.speed_override == 1000000:
                return "1g"
            elif self.speed_override == 2500000:
                return "2.5g"
            elif self.speed_override == 5000000:
                return "5g"
            elif self.speed_override == 10000000:
                return "10g"
            else:
                raise NotImplemented(
                    "Unknown link speed override {}".format(self.speed_override)
                )
        if self.speed.startswith("100base"):
            return "100M"
        if self.speed[1] == "g":
            return self.speed[:2].upper()
        if self.speed[2] == "g":
            return self.speed[:3].upper()
        return self.speed[:4].upper()

    @property
    def tupl(self):
        t = name_to_tuple(self.ifname)
        if t[0] == "Port-Channel":
            return ("A",) + t[1:]
        return t

    def __lt__(self, other):
        return self.tupl < other.tupl

    def __eq__(self, other):
        return self.tupl == other.tupl

    def same_as(self, other):
        return True  # FIXME


class DistIface(Iface):
    def __init__(self, this, other, iface, untagged, access_vlans):
        self.this = this
        self.core = None
        self.untagged = untagged
        self.access_vlans = access_vlans
        super().__init__(this, iface, other)

    def __repr__(self):
        return "%s: (%s -> %s) %s [ %s ]" % (
            self._iface["name"],
            self._this,
            self.other,
            self.untagged,
            "|, ".join(map(str, self.access_vlans)),
        )

    def vlans(self, vlans):
        for vlan in vlans.values():
            if vlan.vid in self.access_vlans or vlan.sitewide:
                yield vlan


class AccessIface(Iface):
    def __init__(
        self,
        this,
        iface,
        other,
        vlans,
        untagged,
        enabled=True,
        tags=[],
        sitewide=True,
    ):
        self._vlans = vlans
        self.untagged = untagged
        self.vlan_all = (
            (iface.get("mode") or {}).get("value", None) == "tagged-all"
            and len(vlans) == 0
            or ("uplink" in tags)
        )
        self.vlan_names = map(lambda a: "V%d" % a, self._vlans or [])
        self.add_sitewide = sitewide
        self.enabled = enabled
        self.tagged = set(vlans)
        self.hybrid = untagged and len(set(vlans) - set([untagged])) > 0
        super().__init__(this, iface, other)

    def __repr__(self):
        return "%s: (%s -> %s) %s [ %s ] %s speed" % (
            self.ifname,
            self._this,
            self._remote,
            self._iface.get("mode"),
            str(self.untagged) + "|" + " , ".join(map(str, self._vlans)),
            self.get_speed(),
        )

    def to_dict(self):
        return {
            "netbox_id": self._iface["id"],
            "name": self.ifname,
            "remote": self._remote,
            "tags": self.tags,
            "enabled": self.enabled,
            "vlan_tagged": sorted(list(self.tagged)),
            "vlan_hybrid": self.hybrid,
            "vlan_all": self.vlan_all,
            "vlan_untagged": self.untagged,
            "is_lag_master": self.is_lag_master,
            "is_virtual": self.is_virtual,
        }

    def update_vlan_all(self, access_vlans):
        if set(access_vlans) == set(self._vlans):
            self.vlan_all = True

    def vlans(self, vlans, untagged=False):
        for vlan in list(vlans.values()):
            if vlan.vid == self.untagged:
                if untagged:
                    yield vlan
                continue
            if vlan.vid in self._vlans or (vlan.sitewide and self.add_sitewide):
                yield vlan

    def vlans_nositewide(self, vlans):
        for vlan in vlans.values():
            if vlan.vid == self.untagged:
                continue
            if vlan.vid in self._vlans:
                yield vlan


class CoreIface(Iface):
    def __init__(self, this, other, iface, pfx4, pfx6):
        self.dist = None
        self.ip4 = pfx4
        self.ip6 = pfx6
        super().__init__(this, iface, other)
        self.vlifname = self.ifname

    def __repr__(self):
        return "%s: (%s -> %s) [%s, %s]" % (
            self.ifname,
            self._this,
            self._remote,
            self.ip4,
            self.ip6,
        )


class LagMemberIface(Iface):
    def __init__(self, iface, lagname):
        self.lagname = lagname
        super().__init__(None, iface, None)

    def __repr__(self):
        return "LagMemberIface (%s, %s)" % (self.ifname, self.lagname)

    def to_dict(self):
        return {
            "name": self.ifname,
            "lagname": self.lagname,
            "is_lag_slave": True,
        }


class UnusedIface(Iface):
    def __init__(self, ifname):
        self.ifname = ifname

    def __repr__(self):
        return "UnusedIface (%s)" % (self.ifname)
