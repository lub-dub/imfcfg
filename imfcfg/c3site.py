import re


class Site(object):
    pfx6 = "2001:db8:1337:%d::/64"
    gw6 = "2001:db8:1337:%d::1"
    loiso = "49.0000.0049.0040.%04d.00"
    l2vlan = 3500

    # "slug" field in netbox
    ROLE_DISTRIBUTION_SWITCH = "distribution-switch"
    ROLE_BORDER_ROUTER = "router"
    ROLE_ACCESS_SWITCH = "access-switch"
    ROLE_WIFI_ROUTER = "wifi-router"

    UNUSED_IFACE_WHITELIST = re.compile(r"(xe|et|ge)-.*")
    VLAN_IFACE_RE = re.compile(r"[Vv]lan|irb\.|(\d+)")

    def gateway_for_vlan(self, device, vid):
        if device.role == "router":
            return 1
        return None

    def is_vlan_origin(self, device, vid):
        # TODO make it parse from a config file
        return device.role == "router"

    def set_l2vlan(self, vlan):
        self.l2vlan = vlan

    def classify_device(self, device):
        slug = device.get("device_role").get("slug")
        if slug == self.ROLE_ACCESS_SWITCH:
            device.role = "access"
        elif slug == self.ROLE_DISTRIBUTION_SWITCH:
            device.role = "distro"
        elif slug == self.ROLE_BORDER_ROUTER:
            device.role = "router"
        elif slug == self.ROLE_WIFI_ROUTER:
            device.role = "wifi-router"
        else:
            device.role = None
