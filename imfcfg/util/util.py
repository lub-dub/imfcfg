import re
from functools import namedtuple, reduce
import ipaddress as ipaddr
import passlib.hash


def net2ip(n):
    """Returns the first IP in a given network"""
    net = ipaddr.ip_interface(n)
    return net.ip


def nin(n1, n2):
    """Returns True if n1 is a subnet of (or equal to) n2"""
    return ipaddr.ip_network(n1) in ipaddr.ip_network(n2)


def nethost(net, addr=None, offset=None, nomask=False, mask=False):
    """jinja2 filter to mangle IP prefixes, addr to the new offset inside the network
    Offset add this offset to the current address, nomask don't print with the network mask, if mask is true
    return the mask and not the address.
    """
    net = ipaddr.ip_interface(str(net))

    if addr == 0:
        net = ipaddr.ip_interface(
            f"{net.network.network_address}/{net.network.prefixlen}"
        )
    elif addr is not None:
        if addr == 1:
            net = ipaddr.ip_interface(
                f"{next(net.network.hosts())}/{net.network.prefixlen}"
            )
        else:
            generator = net.network.hosts()
            hosts = [next(generator) for _ in range(addr)]
            net = ipaddr.ip_interface(f"{hosts[addr-1]}/{net.network.prefixlen}")

    if offset is not None:
        net = net + offset

    if nomask:
        return net.ip
    if mask:
        return net.netmask
    return net


def is_junos_els(dev):
    if dev["device_type"]["slug"].startswith("ex2300"):
        return True
    if dev["device_type"]["slug"].startswith("ex3400"):
        return True
    if dev["device_type"]["slug"].startswith("ex4100"):
        return True
    if dev["device_type"]["slug"].startswith("ex4300"):
        return True
    if dev["device_type"]["slug"].startswith("juniper-"):
        return True
    if dev["device_type"]["slug"].startswith("ex4600"):
        return True
    if dev["device_type"]["slug"].startswith("juniper-qfx51"):
        return True
    return False


def to_dict(v):
    if isinstance(v, set):
        v = sorted(list(v))
    if isinstance(v, list):
        return [to_dict(v) for v in v]
    if isinstance(v, dict):
        return dict([(k, to_dict(v)) for k, v in v.items()])
    return v.to_dict() if hasattr(v, "to_dict") else v


JUNOS_SSH_OUTDATED_PLATFORMS = [
    "ex2200",
    "ex3200",
    "ex3300",
    "ex4200",
]


def is_junos_ssh_outdated(dev):
    dev_type = dev["device_type"]["slug"]
    for m in JUNOS_SSH_OUTDATED_PLATFORMS:
        if dev_type.startswith(m):
            return True
    return False


def get_mgmt_vlan(dev):
    # careful with the extra - so we don't match prodoyolocolo
    if "-yolocolo-" in dev["name"]:
        return 3412
    role = dev["device_role"]["slug"]
    if role == "distribution-switch":
        return 2225
    elif role == "access-switch":
        return 2232
    else:
        raise NotImplemented("Unknown mgmt vlan for role %s" % role)


def get_tags(iface):
    return set(map(lambda x: x["name"], iface.get("tags", [])))


num_re = re.compile(r"[0-9]+")


def name_to_tuple(name):
    """
    convert string "abc123def456ghi" to ("abc",123,"def",456,"ghi") for sorting

    this way, "r1" sorts before "r10"
    """
    from itertools import chain

    strs = num_re.split(name)
    nums = [int(i) for i in num_re.findall(name)] + [None]
    return tuple(list(chain.from_iterable(zip(strs, nums)))[:-1])


def sortifnames(ifaces):
    return sorted(ifaces, key=lambda x: name_to_tuple(x.ifname))


def split_multiline(string, max_len):
    """Returns the input split into a multiline string with a given maximum line length"""
    output_str = ""
    for count, char in enumerate(string):
        if (count % max_len) == 0 and count != 0:
            output_str += "\n"
        output_str += char
    return output_str


def vlanjoin(vlans):
    """
    covert unordered list of vlans to ordered list of vlans and merge consecutive vlans
    into a range.
    input : 1000,1001,1002,1010
    output: 1000-1002,1010
    """

    def inner(state, nxt):
        if len(state) == 0:
            return [(nxt,)]
        last = state[-1]
        if nxt == last[-1] + 1:
            state[-1] = (last[0], nxt)
        else:
            state.append((nxt,))
        return state

    vlans = sorted(vlans)
    ranges = reduce(inner, vlans, [])
    return ",".join([("%d-%d" if len(i) == 2 else "%d") % i for i in ranges])


def hash_password(password, algo="sha512"):
    match algo:
        case "sha1":
            return passlib.hash.sha1_crypt.hash(password)
        case "md5":
            return passlib.hash.md5_crypt.hash(password)
        case "sha256":
            return passlib.hash.sha256_crypt.using(rounds=5000).hash(password)
        case _:
            return passlib.hash.sha512_crypt.using(rounds=5000).hash(password)


def regex_match(pattern, string):
    """Returns true if the expression matches the input string, false if not."""
    return bool(re.match(pattern, string))
