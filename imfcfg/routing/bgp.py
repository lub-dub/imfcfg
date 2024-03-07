def iBGP4(router, routers, rr_client=False):
    """Returns a list of iBGP IPv4 neighbours the given router should establish sessions with"""
    neighbours = []
    for other in routers:
        if router != other.get("name") and (
            "route_server" in other.get("tags") or not rr_client
        ):
            neighbours.append((other.get("primary_ip4") or {}).get("address"))
    return list(filter(lambda a: a != None, neighbours))


def iBGP6(router, routers, rr_client=False):
    """Returns a list of iBGP IPv6 neighbours the given router should establish sessions with"""
    neighbours = []
    for other in routers:
        if router != other.get("name") and (
            "route_server" in other.get("tags") or not rr_client
        ):
            neighbours.append((other.get("primary_ip6") or {}).get("address"))
    return list(filter(lambda a: a != None, neighbours))
