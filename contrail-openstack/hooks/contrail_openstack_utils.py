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
    restart_on_change,
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
        user = {
            "name": auth_info["keystone_admin_user"],
            "domain": {"name": auth_info["keystone_user_domain_name"]},
            "password": auth_info["keystone_admin_password"]
        }
        req_data = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": user
                    }
                },
                "scope": {
                    "project": {
                        "name": auth_info["keystone_admin_tenant"],
                        "domain": {
                            "name": auth_info["keystone_user_domain_name"]
                        }
                    }
                }
            }
        }

    endpoint_v2 = "publicURL"
    endpoint_v3 = "public"
    if config.get("use-internal-endpoints", False):
        endpoint_v2 = "internalURL"
        endpoint_v3 = "internal"

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
            url = service["endpoints"][0][endpoint_v2]
        else:
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == endpoint_v3:
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
    # some code inside neutron-plugin uses auth info from next file
    render("vnc_api_lib.ini", "/etc/contrail/vnc_api_lib.ini", ctx)


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
