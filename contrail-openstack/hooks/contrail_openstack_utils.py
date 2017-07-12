import apt_pkg
from base64 import b64decode
import json
import os
import requests
from six.moves.urllib.parse import urlparse
from socket import gethostbyname

from charmhelpers.core.hookenv import (
    config,
    log,
    WARNING,
    ERROR,
    relation_ids,
    related_units,
)
from charmhelpers.core.host import (
    write_file,
)
from charmhelpers.core.templating import render

apt_pkg.init()
config = config()


def update_service_ips():
    try:
        endpoints = _get_endpoints()
    except Exception as e:
        log("Couldn't detect services ips: " + str(e),
            level=WARNING)
        return False

    changed = {}

    def _check_key(key):
        val = endpoints.get(key)
        if val and val != config.get(key):
            config[key] = val
            changed[key] = val

    _check_key("compute_service_ip")
    _check_key("image_service_ip")
    _check_key("network_service_ip")
    if changed:
        config.save()
        return True

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


def write_configs():
    # don't need to write any configs for nova. only for neutron.

    units = [unit for rid in relation_ids("neutron-api")
                  for unit in related_units(rid)]
    if not units:
        return

    ctx = _get_context()

    # store files in standard path
    ca_path = "/etc/contrail/ssl/certs/ca-cert.pem"
    ssl_ca = ctx["ssl_ca"]
    _save_file(ca_path, ssl_ca)
    ctx["ssl_ca_path"] = ca_path

    render("ContrailPlugin.ini",
           "/etc/neutron/plugins/opencontrail/ContrailPlugin.ini",
           ctx, "root", "neutron", 0o440)


def _get_context():
    ctx = {}

    ip = config.get("api_vip")
    if not ip:
        ip = config.get("api_ip")
    ctx["api_server"] = ip
    ctx["api_port"] = config.get("api_port")

    ssl_ca = _decode_cert("ssl_ca")
    ctx["ssl_ca"] = ssl_ca
    ctx["ssl_enabled"] = (ssl_ca is not None and len(ssl_ca) > 0)
    log("CTX: " + str(ctx))

    auth_info = config.get("auth_info")
    if auth_info:
        ctx.update(json.loads(auth_info))
    return ctx


def _decode_cert(key):
    val = config.get(key)
    if not val:
        return None
    try:
        return b64decode(val)
    except Exception as e:
        log("Couldn't decode certificate from config['{}']: {}".format(
            key, str(e)), level=ERROR)
    return None


def _save_file(path, data):
    if data:
        fdir = os.path.dirname(path)
        if not os.path.exists(fdir):
            os.makedirs(fdir)
        write_file(path, data, perms=0o444)
    elif os.path.exists(path):
        os.remove(path)
