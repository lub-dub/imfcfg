from interfaces.interfaces import *
from nbh import get_nb, TransitIface, TransitUnit

TRANSIT_SUBIF_RE = re.compile(r"(.*)\.(\d+)")


def check_subinf(iface):
    nb = get_nb()
    transitifs = {}
    lag = (iface.get("lag") or {}).get("name")
    ifname = lag or iface.get("name")

    m_subif = TRANSIT_SUBIF_RE.match(ifname)
    unit_id = 0
    phys_ifname = ifname

    # check if it is of type et-0/3/0.1234
    if m_subif:
        unit_id = int(m_subif.groups(0)[1])
        phys_ifname = m_subif.groups(0)[0]
    iid = iface.get("id")
    ips = nb.ip_by_int_id(iid)
    ip4 = None
    ip6 = None
    for ip in ips:
        if ip.get("family", {}).get("value") == 4:
            ip4 = ip.get("address")
        elif ip.get("family", {}).get("value") == 6:
            ip6 = ip.get("address")
        if phys_ifname not in transitifs:
            transitifs[phys_ifname] = TransitIface(
                ifname=phys_ifname, remote=iface.get("description"), units={}
            )
    if ip4 or ip6:
        if unit_id in transitifs[phys_ifname]:
            raise DuplicateIfaceUnitError(
                "%s has unit %d defined multiple times" % (phys_ifname, unit_id)
            )
        transitifs[phys_ifname].units[unit_id] = TransitUnit(
            unit_id, iface.get("description"), ip4, ip6
        )
    return transitifs
