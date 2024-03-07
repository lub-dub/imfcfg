lldp_rem_table = ".1.0.8802.1.1.2.1.4.1.1"
lldp_loc_table = ".1.0.8802.1.1.2.1.3.7.1"
if_table_oper = ".1.3.6.1.2.1.2.2.1.8"
ifx_table = ".1.3.6.1.2.1.31.1.1.1"


def _snmp_get_table(cache, snmpip, tableoid, idxlen):
    data = None
    cachekey = json.dumps([snmpip, tableoid, idxlen]).encode("UTF-8")
    if cachekey in cache:
        cached = json.loads(cache[cachekey].decode("UTF-8"))
        if time.time() < cached.get("ts", 0) + config.get(
            "snmp", "cachetime", fallback=30.0
        ):
            data = cached["data"]

    if data is None:
        community = config.get("snmp", "community")
        if args.trace:
            sys.stderr.write("SNMP WALK: %s %s\n" % (snmpip, tableoid))
        data = subprocess.check_output(
            "snmpwalk -On0 -v2c -c".split() + [community, snmpip, tableoid]
        ).decode("UTF-8")
        cache[cachekey] = json.dumps({"ts": time.time(), "data": data}).encode("UTF-8")
    else:
        if args.trace:
            sys.stderr.write("SNMP CACHE: %s %s\n" % (snmpip, tableoid))

    tableoid = [int(i) for i in tableoid.lstrip(".").split(".")]
    table = {}
    for line in data.splitlines():
        oid, line = line.split(" = ", 1)
        if ":" in line:
            typ, val = line.split(": ", 1)
        else:
            typ, val = "STRING", line

        oid = [int(i) for i in oid.lstrip(".").split(".")]
        assert oid[: len(tableoid)] == tableoid
        oid = oid[len(tableoid) :]
        key, index = oid[0], tuple(oid[1 : 1 + idxlen])

        item = table.setdefault(index, {})
        item[key] = (typ, val)
    return table


def snmp_get_table(snmpip, tableoid, idxlen=1):
    dbpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lldp.cache")
    dblock = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lldp.cache.lock")
    with open(dblock, "w") as lockfd:
        fcntl.lockf(lockfd.fileno(), fcntl.LOCK_EX)
        with dbm.gnu.open(dbpath, "c") as cache:
            return _snmp_get_table(cache, snmpip, tableoid, idxlen)


def snmp_value(data, oid):
    if oid not in data:
        return None
    raw = data[oid]
    if raw[0] == "STRING":
        return raw[1][1:-1].replace(r"\"", '"')
    if raw[0] == "Hex-STRING":
        return raw[1].strip('"').replace(" ", ":")

    return raw[1]


def device_snmp_lldp_neigh(snmpip):
    ports = {}

    try:
        rem_table = snmp_get_table(snmpip, lldp_rem_table, 3)
        loc_table = snmp_get_table(snmpip, lldp_loc_table)
    except subprocess.CalledProcessError:
        return ports
    except FileNotFoundError:
        return ports

    for index, vals in rem_table.items():
        loc_port = loc_table[(index[1],)]
        loc_port_id = snmp_value(loc_port, 3)

        rem_mac = snmp_value(vals, 5)
        rem_name = snmp_value(vals, 9)
        rem_port = snmp_value(vals, 7)
        rem_model = snmp_value(vals, 10)

        suffix = ".congress.ccc.de"
        if rem_name.endswith(suffix):
            rem_name = rem_name[: -len(suffix)]

        # sys.stderr.write('%-20s -> %-20s %-18s %s\n' % (loc_port_id, rem_name, rem_mac, rem_port))
        assert loc_port_id not in ports
        ports[loc_port_id] = {
            "remote_mac": rem_mac,
            "remote_name": rem_name,
            "remote_port": rem_port,
            "remote_model": rem_model,
        }
    return ports


def device_interface_status(devname):
    tvars = {}
    device, ip4, ip6 = loadDeviceData(tvars, devname)
    snmpip = ip4.split("/")[0]

    ports = {}

    try:
        if_table = snmp_get_table(snmpip, ifx_table)
        oper_table = snmp_get_table(snmpip, if_table_oper, 0)
    except subprocess.CalledProcessError:
        return ports
    except FileNotFoundError:
        return ports

    for index, vals in if_table.items():
        if_name = snmp_value(vals, 1)
        if_speed = int(snmp_value(vals, 15))
        if_prsnt = int(snmp_value(vals, 17)) == 1
        if_descr = snmp_value(vals, 18)

        if_state = int(oper_table[tuple()][index[0]][1])

        if_speed_str = {
            0: "",
            100: "100M",
            1000: "1G",
            2500: "2.5G",
            5000: "5G",
            10000: "10G",
            40000: "40G",
            100000: "100G",
        }.get(if_speed, str(if_speed))

        ports[if_name] = {
            "description": if_descr,
            "present": if_prsnt,
            "state": if_state,
            "speed": if_speed,
            "speed_str": if_speed_str,
        }
    return ports


def device_pair_lldp(devname):
    tvars = {}
    device, ip4, ip6 = loadDeviceData(tvars, devname)
    snmpip = ip4.split("/")[0]

    ifs_lldp = device_snmp_lldp_neigh(snmpip)
    ifs_netbox = nb.int_by_device_name(devname)
    ifs_netbox = dict((i["name"], i) for i in ifs_netbox)

    keys = sorted(set(ifs_netbox.keys()) | set(ifs_lldp.keys()), key=name_to_tuple)
    for ifname in keys:
        if_netbox = ifs_netbox.get(ifname, None)
        if_lldp = ifs_lldp.get(ifname, None)
        descr = if_netbox["description"]
        remote = None
        remote_port = None
        lldp_target_id = None
        tags = get_tags(iface)

        if if_netbox is not None:
            fflabel = if_netbox["type"]["label"]
            if fflabel in ["Link Aggregation Group (LAG)", "Virtual"]:
                continue

            remote = iface_get_remote_device(if_netbox)
            remote_port = (
                (if_netbox.get("interface_connection") or {}).get("interface") or {}
            ).get("name", None)

        if if_lldp is not None:
            lldp_nb_ifaces = nb.int_by_device_name(if_lldp["remote_name"])
            lldp_nb_ifaces = dict([(i["name"], i) for i in lldp_nb_ifaces])

            if if_lldp["remote_port"] in lldp_nb_ifaces:
                lldp_target_id = lldp_nb_ifaces[if_lldp["remote_port"]]["id"]
            else:
                for xifname, iface in lldp_nb_ifaces.items():
                    if "uplink" in tags:
                        lldp_target_id = iface["id"]
                        if_lldp["remote_port"] = "%s (%s?)" % (
                            if_lldp["remote_port"],
                            iface["name"],
                        )
                        # sys.stderr.write('guessed iface %s for device %s\n' % (iface['name'], if_lldp['remote_name']))
                        break

        yield ifname, if_netbox, remote, remote_port, descr, if_lldp, lldp_target_id


def device_sync_lldp(devname):
    for (
        ifname,
        if_netbox,
        remote,
        remote_port,
        descr,
        if_lldp,
        lldp_target_id,
    ) in device_pair_lldp(devname):
        netbox_device, lldp_device = None, None

        if if_netbox is not None:
            if remote is None:
                netbox_port = None
                netbox_info = "--"
            else:
                netbox_device = remote["name"]
                netbox_port = remote_port
                netbox_info = "%s %% %s" % (netbox_device, netbox_port)
        else:
            netbox_info = "-- DOES NOT EXIST --"

        if if_lldp is not None:
            lldp_device = if_lldp["remote_name"]
            lldp_port = if_lldp["remote_port"]
            lldp_info = "%s %% %s" % (lldp_device, lldp_port)
        else:
            lldp_info = "--"

        if lldp_device is None and netbox_device is None:
            continue
        color = "31"
        if lldp_device == netbox_device:
            color = "32"
        print(
            "\033[%sm%-16s | %-40s | %-40s\033[m"
            % (color, ifname, netbox_info, lldp_info)
        )
    sys.exit(0)
