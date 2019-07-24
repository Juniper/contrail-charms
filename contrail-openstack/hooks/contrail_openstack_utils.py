import json
import os
import sys
from socket import gethostbyname
from subprocess import CalledProcessError, check_call, check_output

import pkg_resources
import requests
from six.moves.urllib.parse import urlparse

import docker_utils
from charmhelpers.core.hookenv import (
    config,
    log,
    WARNING,
    INFO,
    relation_ids,
    relation_get,
    related_units,
    leader_get,
    leader_set,
    application_version_set,
)
from charmhelpers.core.host import (
    restart_on_change,
    service_restart,
    write_file,
)
from charmhelpers.core.templating import render

config = config()


PACKAGE_CODENAMES = {
    'nova': {
        '12': 'liberty',
        '13': 'mitaka',
        '14': 'newton',
        '15': 'ocata',
        '16': 'pike',
        '17': 'queens',
        '18': 'rocky',
    },
    'neutron': {
        '7': 'liberty',
        '8': 'mitaka',
        '9': 'newton',
        '10': 'ocata',
        '11': 'pike',
        '12': 'queens',
        '13': 'rocky',
    },
    'heat': {
        '5': 'liberty',
        '6': 'mitaka',
        '7': 'newton',
        '8': 'ocata',
        '9': 'pike',
        '10': 'queens',
        '11': 'rocky',
    },
}

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
    neutron = _is_related_to("neutron-api")
    heat = _is_related_to("heat")
    if not neutron and not heat:
        return

    ctx = get_context()

    keystone_ssl_ca = ctx.get("keystone_ssl_ca")
    path = "/etc/contrail/keystone/ssl/ca-cert.pem"
    _save_file(path, keystone_ssl_ca)
    if keystone_ssl_ca:
        ctx["keystone_ssl_ca_path"] = path

    if neutron:
        render("ContrailPlugin.ini",
               "/etc/neutron/plugins/opencontrail/ContrailPlugin.ini",
               ctx, "root", "neutron", 0o440)
    # some code inside neutron-plugin/heat uses auth info from next file
    render("vnc_api_lib.ini", "/etc/contrail/vnc_api_lib.ini", ctx)


def _is_related_to(rel_name):
    units = [unit for rid in relation_ids(rel_name)
                  for unit in related_units(rid)]
    return True if units else False


def get_context():
    ctx = {}
    ctx["api_servers"] = [relation_get("private-address", unit, rid)
                          for rid in relation_ids("contrail-controller")
                          for unit in related_units(rid)]
    ctx["api_port"] = config.get("api_port")
    # TODO: think about ssl here
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


def deploy_openstack_code(image, env_dict=None):
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
    docker_utils.run(image, tag, volumes, env_dict=env_dict)
    try:
        version = docker_utils.get_contrail_version(image, tag)
        application_version_set(version)
    except CalledProcessError as e:
        log("Couldn't detect installed application version: " + str(e))


def nova_patch():
    version = get_openstack_version_codename('nova')
    if version != 'ocata':
        # patch is required only for Ocata.
        # lower versions are not supported.
        # next versions do not requires the patch
        log("this nova version is unsupported: {}".format(version), level=INFO)
        return

    import nova
    nova_path = os.path.dirname(nova.__file__)
    pwd = os.getcwd()
    base_cmd = ["/usr/bin/patch", "-p", "2", "-i", pwd + "/files/nova.diff", "-d", nova_path, "-b"]
    try:
        check_call(base_cmd + ["-f", "--dry-run"])
    except Exception as e:
        # already patched
        log("nova is already patched: {exc}".format(exc=e), level=INFO)
        return

    check_call(base_cmd)
    service_restart('nova-compute')

    # TODO: un-patch
    # patch -p 2 -i files/nova.diff -d ${::nova_path} -b -R -f --dry-run
    # patch -p 2 -i files/nova.diff -d ${::nova_path} -b -R


def get_openstack_version_codename(dist):
    try:
        version = pkg_resources.get_distribution(dist).version
        return PACKAGE_CODENAMES[dist][version.split('.')[0]]
    except Exception as e:
        # nova is not installed
        log("Version of {} couldn't be derived: {}".format(dist, e), level=WARNING)
        return None
