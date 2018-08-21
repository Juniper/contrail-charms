import json
import os
import sys
from socket import gethostbyname
from subprocess import CalledProcessError, check_call

import pkg_resources
import requests
from six.moves.urllib.parse import urlparse

import docker_utils
from charmhelpers.core.hookenv import (
    config,
    log,
    WARNING,
    relation_ids,
    relation_get,
    related_units,
    leader_get,
    leader_set,
    application_version_set,
)
from charmhelpers.core.host import (
    restart_on_change,
    write_file,
)
from charmhelpers.core.templating import render

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

    # this is still needed for version < 4.1.1
    ip = config.get("api_vip")
    if not ip:
        ip = config.get("api_ip")
    ctx["api_server"] = ip

    ctx["api_servers"] = [relation_get("private-address", unit, rid)
                          for rid in relation_ids("contrail-controller")
                          for unit in related_units(rid)]
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


def deploy_openstack_code(image):
    tag = config.get('image-tag')
    docker_utils.pull(image, tag)

    # remove previous attempt
    docker_utils.remove_container_by_image(image)

    paths = [path for path in sys.path if 'packages' in path]
    path = paths[-1]
    volumes = [
        # container will copy libraries to /opt/plugin/site-packages
        # that is PYTHONPATH in the system
        "{}:/opt/plugin/site-packages".format(path),
        # container will copy tools to /opt/plugin/bin
        # that is /usr/bin in the system
        "/usr/bin:/opt/plugin/bin",
    ]
    docker_utils.run(image, tag, volumes)
    try:
        version = docker_utils.get_contrail_version(image, tag)
        application_version_set(version)
    except CalledProcessError as e:
        log("Couldn't detect installed application version: " + str(e))


def nova_patch():
    # patch nova for DPDK
    try:
        import nova
    except Exception:
        # nova is not installed
        return

    nova_version = pkg_resources.get_distribution("nova").version
    if nova_version.split('.')[0] != 15:
        # patch is required only for Ocata.
        # lower versions are not supported.
        # next versions do not requires the patch
        return

    nova_path = os.path.dirname(nova.__file__)
    try:
        check_call("patch -p 2 -i files/nova.diff -d {} -b -f --dry-run".format(nova_path))
    except Exception:
        # already patched
        return

    check_call("patch -p 2 -i files/nova.diff -d {} -b".format(nova_path))

    # TODO: un-patch
    # patch -p 2 -i files/nova.diff -d ${::nova_path} -b -R -f --dry-run
    # patch -p 2 -i files/nova.diff -d ${::nova_path} -b -R
