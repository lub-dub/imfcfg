from vlans import *
from interfaces import *
from util import *
from cachedpynetbox import pynetbox

from collections import namedtuple

FakeDevice = namedtuple("FakeDevice", ["name", "role"])

TransitIface = namedtuple("TransitIface", "ifname remote units")
TransitUnit = namedtuple("TransitUnit", "unitnum unitdescr ip4 ip6")

ROLE_DISTRIBUTION_SWITCH = "distribution-switch"
ROLE_BORDER_ROUTER = "router"
ROLE_ACCESS_SWITCH = "access-switch"
ROLE_WIFI_ROUTER = "wifi-router"
ROLE_AP = "accesspoint"

UNUSED_IFACE_WHITELIST = re.compile(r"((xe|et|ge)-|Ethernet).*")
VLAN_IFACE_RE = re.compile(r"([Vv]lan|irb\.)([0-9]+)")
TRANSIT_SUBIF_RE = re.compile(r"(.*)\.(\d+)")

nb = None


def store_nb(n_nb):
    global nb
    nb = n_nb


def get_nb():
    global nb
    return nb


def iface_get_remote_name(iface):
    if iface["type"]["value"] == "lag":
        members = nb.lag_members_by_iface(iface)
        if len(members) > 0:
            iface = nb.lag_members_by_iface(iface)[0]
        else:
            return None
    return ((iface.get("connected_endpoints") or [{}])[0].get("device") or {}).get(
        "name"
    )


def iface_get_remote_device(iface):
    remote = iface_get_remote_name(iface)
    if not remote:
        return None

    remote = nb.dev_by_name(remote)
    if len(remote) > 1:
        raise ValueError("port %r has more than 1 remote device" % (iface))
    if len(remote) == 1:
        return remote[0]
    return None


def iter_iface_down(device, rootiface):
    visited = set([device])
    current_device = nb.dev_by_name(device)[0]
    default_access_vlan = current_device["custom_fields"].get(
        "default_access_vlan", None
    )
    ifqueue = [(device, rootiface, default_access_vlan)]

    current_role = current_device.get("device_role").get("slug")
    # always iter down to access switches, if we are a a core devices also
    # iterate down into access switches
    down_stream_role = [ROLE_ACCESS_SWITCH]
    if current_role not in [ROLE_ACCESS_SWITCH, ROLE_DISTRIBUTION_SWITCH]:
        down_stream_role.append(ROLE_DISTRIBUTION_SWITCH)

    while len(ifqueue) > 0:
        dev, iface, default_access_vlan = ifqueue.pop(0)
        remote = iface_get_remote_device(iface)
        if remote:
            remote_role = remote.get("device_role").get("slug")
            # only iter downstream to devices that we know are below us
            if remote_role in down_stream_role and not remote["name"] in visited:
                visited.add(remote["name"])
                # append all interfaces of remote device to queue
                for rmtif in nb.int_by_device_name(remote["name"]):
                    # if no default_access_vlan is defined iherit it from the parent
                    ifqueue.append(
                        (
                            remote["name"],
                            rmtif,
                            remote["custom_fields"].get(
                                "default_access_vlan", default_access_vlan
                            ),
                        )
                    )

        yield dev, iface, remote, default_access_vlan


def is_facing_core(device):
    for dev, depth in iter_devices_up(device["name"]):
        if dev.get("role").get("slug") not in [
            ROLE_ACCESS_SWITCH,
            ROLE_DISTRIBUTION_SWITCH,
        ]:
            return dev
    return None


def iter_devices_up(device, distro_only=True):
    """Start at some switch, iterate devices towards core"""

    device = nb.dev_by_name(device)

    devqueue = [(device[0], 0)]
    visited = set([device[0]["name"]])

    while len(devqueue) > 0:
        device, depth = devqueue.pop(0)
        yield device, depth

        role = device.get("device_role").get("slug")
        # if not access_switch or distribution_switch core is found
        if role not in [ROLE_ACCESS_SWITCH, ROLE_DISTRIBUTION_SWITCH]:
            return

        for iface in nb.int_by_device_name(device["name"]):
            enabled = iface.get("enabled", True)
            if not enabled:
                continue
            remote = iface_get_remote_device(iface)
            if remote is None:
                continue
            if remote["name"] in visited:
                continue
            # if we started at a distri switch we should not iter down into access switches
            if distro_only and role == ROLE_ACCESS_SWITCH:
                continue

            devqueue.append((remote, depth + 1))
            visited.add(remote["name"])


def find_default_vlan(device):
    current_device = nb.dev_by_name(device)[0]
    role = current_device.get("device_role").get("slug")
    for device, depth in iter_devices_up(device, role == ROLE_DISTRIBUTION_SWITCH):
        vlanid = device["custom_fields"].get("default_access_vlan", None)
        if vlanid is None:
            continue
        return vlanid


def iface_get_untagged(device, iface, implicit=True):
    explicit = (iface.get("untagged_vlan") or {}).get("vid")
    if explicit:
        return explicit
    if implicit:
        if iface["type"]["value"] not in ["Link Aggregation Group (LAG)", "Virtual"]:
            current_device = nb.dev_by_name(device)[0]
            role = current_device.get("device_role").get("slug")

            return find_default_vlan(device)


def get_vlans_on_iface(vlans_all, device, iface):
    vlans = set([])
    vlans_root = set([])

    remote0 = (None,)

    current_device = nb.dev_by_name(device)[0]
    role = current_device.get("device_role").get("slug")

    # walk interace down
    for dev, deviface, remote, default_access_vlan in iter_iface_down(device, iface):
        if remote0 == (None,):
            remote0 = remote

        # If there is a remote, mark it as the origin for all vlans
        # TODO: if the depth is more then 1 mark the interface as tagged_all somehow
        if remote is not None and (remote_core := is_facing_core(remote)) is not None:
            for vid in vlans_all:
                if site.is_vlan_origin(
                    FakeDevice(remote_core["name"], remote_core["device_role"]["slug"]),
                    vid,
                ):
                    vlans_root.add(vid)

        # vlans to add to the interface
        add_vlans = set()
        # check for tagged vlans
        tagged_vlans = deviface.get("tagged_vlans", [])
        if len(tagged_vlans) > 0:
            add_vlans.update([v.get("vid") for v in tagged_vlans])

        # check for untagged vlans
        untagged = iface_get_untagged(dev, deviface, False)
        if untagged is not None:
            add_vlans.add(untagged)
        # no tagged nor untagged vlans -> so default vlan
        elif len(tagged_vlans) < 1 and default_access_vlan is not None:
            add_vlans.add(default_access_vlan)

        # probably just affects non-standard management vlan interfaces
        m = VLAN_IFACE_RE.match(deviface["name"])
        if m:
            add_vlans.add(int(m.groups()[1]))

        # add queried vlans to the interface
        vlans.update(add_vlans)
        tags = get_tags(iface)
    # if we have a remote use the explict configured untagged, same if we have tagged vlans or
    # a uplink tag, otherwise iterate upwards until we find the first device with a
    # default_access_vlan
    untagged = iface_get_untagged(
        device,
        iface,
        remote0 is None
        and len(iface.get("tagged_vlans", [])) == 0
        and "uplink" not in tags,
    )

    if None in vlans:
        vlans.remove(None)
    return untagged, set(vlans), set(vlans_root), remote0


def collect_access_vlans(t_switch):
    global nb
    accessifs = []
    access_vlans = set([])
    lagifs = []
    lags = {}
    ifdata = {}
    vlan_directions = {}

    # Gather all known vlans from netbox
    vlans_all = set([vlan["vid"] for vlan in nb.vlans()])

    # get all interfaces form netbox
    for iface in nb.int_by_device_name(t_switch):
        # get vlans on the device
        untagged, vlans, vlans_root, remote = get_vlans_on_iface(
            vlans_all, t_switch, iface
        )
        ifdata[iface["name"]] = (untagged, vlans, remote)

        for vid in vlans | vlans_root:
            if vid is None:
                continue
            ## store vlan -> interface mapping (for for example HP)
            vlan_directions.setdefault(vid, set([])).add(iface["name"])

    # Second pass
    for iface in nb.int_by_device_name(t_switch):
        enabled = iface.get("enabled", True)
        lag = (iface.get("lag") or {}).get("name")

        if lag:
            lagifs.append(LagMemberIface(iface, lag))
            continue

        ifname = iface.get("name")
        untagged, vlans, remote = ifdata[ifname]
        for vid, ports in vlan_directions.items():
            if len(ports) == 1:
                continue
            if iface["name"] in ports:
                vlans.add(vid)

        tags = get_tags(iface)
        description = remote.get("name") if remote else iface.get("description")
        sitewide = remote == None
        accessifs.append(
            AccessIface(
                t_switch,
                iface,
                description,
                vlans,
                untagged,
                enabled=enabled,
                tags=tags,
                sitewide=sitewide,
            )
        )
        access_vlans.update(vlans)
        access_vlans.add(untagged)

    if None in access_vlans:
        access_vlans.remove(None)

    accessifs = sorted(accessifs, key=lambda x: name_to_tuple(x.ifname))
    lagifs = sorted(lagifs, key=lambda x: name_to_tuple(x.ifname))
    return accessifs, lagifs, access_vlans


def compute_vlan_ifaces(ifaces, access_vlans):
    vlans_tagged = {}
    vlans_untagged = {}

    for iface in ifaces:
        if iface.is_virtual:
            continue
        iface.update_vlan_all(access_vlans)
        if iface.untagged is not None:
            vlans_untagged.setdefault(iface.untagged, set([])).add(iface.ifname)
        tagged_vlans = iface.tagged
        for vid in tagged_vlans:
            vlans_tagged.setdefault(vid, set([])).add(iface.ifname)
        if iface.vlan_all:
            for vid in access_vlans:
                vlans_tagged.setdefault(vid, set([])).add(iface.ifname)

    return vlans_untagged, vlans_tagged
