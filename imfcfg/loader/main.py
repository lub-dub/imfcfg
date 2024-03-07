from nbh import *
from util import *
from interfaces import *


ROLE_DISTRIBUTION_SWITCH = "distribution-switch"
ROLE_BORDER_ROUTER = "router"
ROLE_ACCESS_SWITCH = "access-switch"
ROLE_WIFI_ROUTER = "wifi-router"
ROLE_AP = "accesspoint"

UNUSED_IFACE_WHITELIST = re.compile(r"((xe|et|ge)-|Ethernet).*")
VLAN_IFACE_RE = re.compile(r"([Vv]lan|irb\.)([0-9]+)")
TRANSIT_SUBIF_RE = re.compile(r"(.*)\.(\d+)")


def loadVlans():
    nb = get_nb()

    prefixes = {}
    prefixnew = {}

    nbprefixes = nb.prefixes()

    for p in nbprefixes:
        if p["status"]["value"] == "active" and p["vlan"]:
            vid = int(p["vlan"]["vid"])

            firewall = p["custom_fields"].get("firewall", None)
            if isinstance(firewall, dict):
                firewall = firewall["label"]

            prefixnew.setdefault(vid, []).append(
                {
                    "prefix": ipaddr.ip_network(p["prefix"]),
                    "name": p["vlan"]["name"],
                    "firewall": firewall or "public",
                    "dhcp": p["custom_fields"].get("dhcp", True),
                }
            )
    return VlanDict(nb, prefixnew)


def loadPrefixes():
    nb = get_nb()
    prefixes = {}
    nbprefixes = nb.prefixes()
    for p in nbprefixes:
        if p["status"]["value"] == "active":
            if p["vlan"]:
                # TODO check if we need to use .value like with ip-address
                if p["family"]["value"] == 4:
                    vid = p["vlan"]["vid"]
                    fw = "public"
                    if p["custom_fields"].get("firewall", None):
                        fw = p["custom_fields"]["firewall"]
                    dhcp = True
                    if p["custom_fields"].get("dhcp", None) is not None:
                        dhcp = p["custom_fields"]["dhcp"]
                    if ipaddr.ip_network(p["prefix"]).prefixlen < 30:
                        prefixes[vid] = {
                            "v4": p["prefix"],
                            "v6": site.pfx6 % vid,
                            "name": p["vlan"]["name"],
                            "fw": fw,
                            "dhcp": dhcp,
                        }
                    else:
                        prefixes[vid] = {
                            "v4": p["prefix"],
                            "v6": site.pfx6 % vid,
                            "name": p["vlan"]["name"],
                            "fw": fw,
                            "dhcp": dhcp,
                        }
                elif p["family"] == 6:
                    pass
    return prefixes


def loadDeviceData(tvars, device):
    nb = get_nb()
    dev = nb.dev_by_name(device)
    if len(dev) != 1:
        raise NoSuchDeviceError(device)

    dev[0]["tags"] = get_tags(dev[0])
    ip4 = (dev[0].get("primary_ip4") or {}).get("address")
    ip6 = (dev[0].get("primary_ip6") or {}).get("address")
    if not ip4:
        raise NoSuchDeviceError(device)
    dev[0]["poe"] = nb.has_poe(dev[0]["device_type"]["display"])

    tvars.update(hostname=device)
    return dev[0], ip4, ip6


def loadSwitchData(tvars, switch):
    dev, ip4, ip6 = loadDeviceData(tvars, switch)

    tvars.update(mgmt_ip4=ip4)
    tvars.update(mgmt_ip6=ip6)

    accessifs, lagifs, access_vlans = collect_access_vlans(switch)
    vlans_untagged, vlans_tagged = compute_vlan_ifaces(accessifs, access_vlans)

    tvars.update(device=dev)
    tvars.update(accessifs=accessifs)
    tvars.update(lagifs=lagifs)
    tvars.update(access_vlans=access_vlans)
    tvars.update(vlans_untagged=vlans_untagged)
    tvars.update(vlans_tagged=vlans_tagged)


def loadRouterData(tvars, router):
    nb = get_nb()
    dev, ip4, ip6 = loadDeviceData(tvars, router)
    # use the last octect of the ipv4 address as uniq identifer
    loopback = ipaddr.IPv4Interface(ip4)
    siteid = loopback.ip._ip & 0xFF
    # normalise down to whole numbers
    nodeid = siteid
    if nodeid > 128:
        nodeid = nodeid - 128

    tvars.update(siteid=siteid)
    tvars.update(
        lo0={
            "inet": ip4,
            "inet6": ip6,
            "iso": site.loiso % siteid,
            "node4": 100 + nodeid,
            "node6": 200 + nodeid,
        }
    )

    coreifs = []
    distifs = []
    accessifs = []
    # physical ifname -> TransitIface
    transitifs = {}
    lagifs = []
    unusedifs = []
    active_vlans = set()
    lags = {}
    lags_circuit = {}

    vlans_all = set([vlan["vid"] for vlan in nb.vlans()])

    for iface in nb.int_by_device_name(router):
        remote = iface_get_remote_name(iface)
        if iface["name"].startswith("Loopback"):
            continue

        lag = (iface.get("lag") or {}).get("name")
        ifname = lag or iface.get("name")

        m = VLAN_IFACE_RE.match(ifname)
        if m:
            active_vlans.add(int(m.groups()[1]))
        tags = get_tags(iface)
        if (
            (not remote)
            and iface.get("mode") == None
            and iface.get("description") in [None, ""]
        ):
            # interface hasn't been assigned access mode and is not connected -> unused interface
            if UNUSED_IFACE_WHITELIST.match(ifname) and not lag:
                unusedifs.append(UnusedIface(ifname=ifname))
            continue
        elif not remote and "uplink" in tags:
            if lag:
                lagifs.append(LagMemberIface(iface, lag))
                lags_circuit[lag] = iface.get("description")
            else:
                transitifs |= check_subinf(iface)
            continue
        elif lag:
            ifobj = LagMemberIface(iface, lag)
            lagifs.append(ifobj)
            if lag not in lags:
                lags[lag] = ifobj
            else:
                if ifobj.same_as(lags[lag]):
                    continue
                raise ValueError(
                    "LAG members mismatch, device %s port %s" % (router, iface["name"])
                )
            continue
        elif not remote:
            ac_vlans = [vlan["vid"] for vlan in iface.get("tagged_vlans", [])]
            ac_untagged = iface_get_untagged(router, iface, len(ac_vlans) == 0)
            accessifs.append(
                AccessIface(
                    router,
                    iface,
                    iface.get("description"),
                    ac_vlans,
                    ac_untagged,
                    sitewide=False,
                )
            )
            if ac_untagged:
                active_vlans.add(ac_untagged)
            active_vlans.update(ac_vlans)
            continue
        remote_name = remote
        remote = nb.dev_by_name(remote)
        if not remote:
            sys.stderr.write(
                "%r interface %r remote named %r not found\n"
                % (router, ifname, remote_name)
            )
            continue
        elif len(remote) > 1:
            sys.stderr.write(
                "%r interface %r has multiple remotes named %r\n"
                % (router, ifname, remote_name)
            )
            continue
        else:
            remote = remote[0]

        remote_role = remote.get("device_role").get("slug")

        if remote_role == ROLE_BORDER_ROUTER and "mlag" not in get_tags(iface):
            ips = nb.ip_by_int_id(iface["id"])
            ip4 = None
            ip6 = None
            tags = get_tags(iface)
            if "fusion" in tags:
                continue
            for ip in ips:
                if ip.get("family", {}).get("value") == 4:
                    ip4 = ip.get("address")
                elif ip.get("family", {}).get("value") == 6:
                    ip6 = ip.get("address")
            tlist, ifobj = coreifs, CoreIface(
                router, remote.get("name"), iface, ip4, ip6
            )
        else:
            untagged, vlans, vlans_root, remote = get_vlans_on_iface(
                vlans_all, router, iface
            )
            active_vlans.update(vlans)
            if remote_role == ROLE_DISTRIBUTION_SWITCH:
                tlist, ifobj = distifs, DistIface(
                    router, remote.get("name"), iface, untagged, vlans
                )
            else:
                tlist, ifobj = accessifs, AccessIface(
                    router, iface, remote.get("name"), vlans, untagged
                )

        tlist.append(ifobj)

    tvars.update(device=dev)
    if "mlag" in dev["tags"]:
        tvars.update(active_vlans=vlans_all)
    else:
        tvars.update(active_vlans=active_vlans)
    tvars.update(coreifs=coreifs)
    tvars.update(distifs=distifs)
    tvars.update(accessifs=accessifs)
    tvars.update(lagifs=lagifs)
    tvars.update(unusedifs=unusedifs)
    tvars.update(transitifs=transitifs)
