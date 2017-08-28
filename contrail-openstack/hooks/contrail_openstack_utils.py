import apt_pkg
import json
import os
import requests
from six.moves.urllib.parse import urlparse
from socket import gethostbyname

from charmhelpers.core.hookenv import (
    config,
    log,
    WARNING,
    relation_ids,
    related_units,
    leader_get,
    leader_set,
)
from charmhelpers.core.host import (
    file_hash,
    restart_on_change,
    service_restart,
    write_file,
)
from charmhelpers.core.templating import render

apt_pkg.init()
config = config()


def update_service_ips():
    try:
        endpoints = _get_endpoints()
    except Exception as e:
        log("Couldn't detect services ips: {exc}".format(exc=e),
            level=WARNING)
        return False

    values = dict()

    def _check_key(key):
        val = endpoints.get(key)
        if val != leader_get(key):
            values[key] = val

    _check_key("compute_service_ip")
    _check_key("image_service_ip")
    _check_key("network_service_ip")
    if values:
        log("services ips has been changed: {ips}".format(ips=values))
        leader_set(**values)
        return True

    log("services ips has not been changed.")
    return False


def _get_endpoints():
    auth_info = config.get("auth_info")
    if auth_info:
        auth_info = json.loads(auth_info)
    if not auth_info or not auth_info.get("keystone_ip"):
        raise Exception("auth_info is not ready.")

    api_ver = int(auth_info["keystone_api_version"])
    if api_ver == 2:
        req_data = {
            "auth": {
                "tenantName": auth_info["keystone_admin_tenant"],
                "passwordCredentials": {
                    "username": auth_info["keystone_admin_user"],
                    "password": auth_info["keystone_admin_password"]}}}
    else:
        req_data = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": auth_info["keystone_admin_user"],
                            "domain": {"id": "default"},
                            "password": auth_info["keystone_admin_password"]
                        }
                    }
                }
            }
        }

    url = "{proto}://{ip}:{port}/{tokens}".format(
        proto=auth_info["keystone_protocol"],
        ip=auth_info["keystone_ip"],
        port=auth_info["keystone_public_port"],
        tokens=auth_info["keystone_api_tokens"])
    r = requests.post(url, headers={'Content-type': 'application/json'},
                      data=json.dumps(req_data), verify=False)
    content = json.loads(r.content)
    result = dict()
    catalog = (content["access"]["serviceCatalog"] if api_ver == 2 else
               content["token"]["catalog"])
    for service in catalog:
        if api_ver == 2:
            # NOTE: 0 means first region. do we need to search for region?
            url = service["endpoints"][0]["publicURL"]
        else:
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    url = endpoint["url"]
                    break
        host = gethostbyname(urlparse(url).hostname)
        result[service["type"] + "_service_ip"] = host
    return result


@restart_on_change({
    "/etc/neutron/plugins/opencontrail/ContrailPlugin.ini": ["neutron-server"],
    "/etc/contrail/keystone/ssl/ca-cert.pem": ["neutron-server"],
})
def write_configs():
    # don't need to write any configs for nova. only for neutron.
    if not _is_related_to("neutron-api"):
        return

    ctx = _get_context()

    keystone_ssl_ca = ctx.get("keystone_ssl_ca")
    path = "/etc/contrail/keystone/ssl/ca-cert.pem"
    _save_file(path, keystone_ssl_ca)
    if keystone_ssl_ca:
        ctx["keystone_ssl_ca_path"] = path

    render("ContrailPlugin.ini",
           "/etc/neutron/plugins/opencontrail/ContrailPlugin.ini",
           ctx, "root", "neutron", 0o440)


def _is_related_to(rel_name):
    units = [unit for rid in relation_ids(rel_name)
                  for unit in related_units(rid)]
    return True if units else False


def _get_context():
    ctx = {}

    ip = config.get("api_vip")
    if not ip:
        ip = config.get("api_ip")
    ctx["api_server"] = ip
    ctx["api_port"] = config.get("api_port")
    ctx["ssl_enabled"] = config.get("ssl_enabled", False)
    log("CTX: " + str(ctx))

    auth_info = config.get("auth_info")
    if auth_info:
        ctx.update(json.loads(auth_info))
    return ctx


def _save_file(path, data):
    if data:
        fdir = os.path.dirname(path)
        if not os.path.exists(fdir):
            os.makedirs(fdir)
        write_file(path, data, perms=0o444)
    elif os.path.exists(path):
        os.remove(path)


def ensure_neutron_api_paste(section, key, value, exist):
    api_paste_path = "/etc/neutron/api-paste.ini"
    lines = list()
    skip = False
    _section = "[{section}]".format(section=section)
    with open(api_paste_path, "r") as f:
        for line in f:
            if _section in line:
                skip = True
            elif line.strip().startswith("["):
                skip = False
            if skip:
                continue

            if line.startswith("keystone"):
                # update is not needed
                if section in line:
                    if exist:
                        return
                    parts = line.split(section)
                    line = parts[0] + parts[1]
                if section not in line:
                    if not exist:
                        return
                    line = "keystone = {section}{sections}".format(
                        section=section, sections=line.split("=")[1])
            lines.append(line)

    if exist:
        lines.append("\n[filter:{section}]\n".format(section=section))
        lines.append("{key} = {value}\n".format(key=key, value=value))

    with open(api_paste_path, "w") as f:
        for line in lines:
            f.write(line)


def tls_changed(cert, key, ca):
    files = {"/etc/contrail/ssl-co/certs/server.pem": cert,
             "/etc/contrail/ssl-co/private/server-privkey.pem": key,
             "/etc/contrail/ssl-co/certs/ca-cert.pem": ca}
    changed = False
    for cfile in files:
        data = files[cfile]
        old_hash = file_hash(cfile)
        _save_file(cfile, data)
        changed |= (old_hash != file_hash(cfile))

    if not changed:
        log("Certificates was not changed.")
        return

    log("Certificates was changed. Rewrite configs and rerun services.")
    config["ssl_enabled"] = (ca is not None and len(ca) > 0)
    config.save()

    if not _is_related_to("neutron-api"):
        return
    write_configs()
    service_restart("neutron-server")
