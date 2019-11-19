import json
import os
import re
import base64
from socket import gaierror, gethostbyname, gethostname, getfqdn
from subprocess import CalledProcessError, check_call, check_output

import netifaces

import docker_utils
from charmhelpers.contrib.network.ip import (
    get_address_in_network,
    get_iface_addr
)
from charmhelpers.core.hookenv import (
    ERROR,
    application_version_set,
    charm_dir,
    config,
    log,
    status_set,
    local_unit
)
from charmhelpers.core.host import (
    file_hash,
    rsync,
    write_file,
)
from charmhelpers.core.templating import render

config = config()


def get_ip(config_param="control-network", fallback=None):
    network = config.get(config_param)
    if network:
        # try to get ip from CIDR
        try:
            ip = get_address_in_network(network, fatal=True)
            return ip
        except Exception:
            pass
        # try to get ip from interface name
        try:
            return get_iface_addr(network, fatal=True)[0]
        except Exception:
            pass

    return fallback if fallback else _get_default_ip()


def _get_default_ip():
    if hasattr(netifaces, "gateways"):
        iface = netifaces.gateways()["default"][netifaces.AF_INET][1]
    else:
        data = check_output("ip route | grep ^default", shell=True).decode('UTF-8').split()
        iface = data[data.index("dev") + 1]
    return netifaces.ifaddresses(iface)[netifaces.AF_INET][0]["addr"]


def fix_hostname():
    hostname = gethostname()
    try:
        gethostbyname(hostname)
    except gaierror:
        ip = get_ip()
        check_call(["sed", "-E", "-i", "-e",
            ("/127.0.0.1[[:blank:]]+/a \\\n" + ip + " " + hostname),
            "/etc/hosts"])


def decode_cert_from_config(key):
    val = config.get(key)
    if not val:
        return None
    return decode_cert(val)


def decode_cert(cert):
    try:
        return base64.b64decode(cert).decode()
    except Exception as e:
        log("Couldn't decode certificate: {}".format(e), level=ERROR)
    return None


def encode_cert(cert):
    return base64.b64encode(cert.encode())


def save_file(path, data, perms=0o400):
    if data:
        fdir = os.path.dirname(path)
        if not os.path.exists(fdir):
            os.makedirs(fdir)
        write_file(path, data, perms=perms)
    elif os.path.exists(path):
        os.remove(path)


def update_services_status(module, services):
    try:
        output = check_output("export CONTRAIL_STATUS_CONTAINER_NAME=contrail-status-{} ; contrail-status".format(module), shell=True).decode('UTF-8')
    except Exception as e:
        log("Container is not ready to get contrail-status: " + str(e))
        status_set("waiting", "Waiting services to run in container")
        return

    statuses = dict()
    group = None
    for line in output.splitlines()[1:]:
        words = line.split()
        if len(words) == 4 and words[0] == "==" and words[3] == "==":
            group = words[2]
            continue
        if len(words) == 0:
            group = None
            continue
        if group and len(words) >= 2 and group in services:
            srv = words[0].split(":")[0]
            statuses.setdefault(group, dict())[srv] = (
                words[1], " ".join(words[2:]))

    for group in services:
        if group not in statuses:
            status_set("waiting",
                       "POD " + group + " is absent in the contrail-status")
            return
        for srv in services[group]:
            if srv not in statuses[group]:
                status_set("waiting",
                           srv + " is absent in the contrail-status")
                return
            status, desc = statuses[group].get(srv)
            if status not in ["active", "backup"]:
                workload = "waiting" if status == "initializing" else "blocked"
                status_set(workload, "{} is not ready. Reason: {}"
                           .format(srv, desc if desc else status))
                return

    status_set("active", "Unit is ready")
    try:
        tag = config.get('image-tag')
        docker_utils.pull("contrail-base", tag)
        version = docker_utils.get_contrail_version("contrail-base", tag)
        application_version_set(version)
    except CalledProcessError as e:
        log("Couldn't detect installed application version: " + str(e))


def json_loads(data, default=None):
    return json.loads(data) if data else default


def apply_keystone_ca(module, ctx):
    ks_ca_path = "/etc/contrail/ssl/{}/keystone-ca-cert.pem".format(module)
    ks_ca_hash = file_hash(ks_ca_path)
    ks_ca = ctx.get("keystone_ssl_ca")
    save_file(ks_ca_path, ks_ca, 0o444)
    ks_ca_hash_new = file_hash(ks_ca_path)
    if ks_ca:
        ctx["keystone_ssl_ca_path"] = "/etc/contrail/ssl/keystone-ca-cert.pem"
    ca_changed = (ks_ca_hash != ks_ca_hash_new)
    if ca_changed:
        log("Keystone CA cert has been changed: {h1} != {h2}"
            .format(h1=ks_ca_hash, h2=ks_ca_hash_new))
    return ca_changed


def get_tls_settings(self_ip):
    hostname = getfqdn()
    cn = hostname.split(".")[0]
    sans = [hostname]
    if hostname != cn:
        sans.append(cn)
    sans_ips = []
    try:
        sans_ips.append(gethostbyname(hostname))
    except:
        pass
    control_ip = self_ip
    if control_ip not in sans_ips:
        sans_ips.append(control_ip)
    res = check_output(['getent', 'hosts', control_ip]).decode('UTF-8')
    control_name = res.split()[1].split('.')[0]
    if control_name not in sans:
        sans.append(control_name)
    sans_ips.append("127.0.0.1")
    sans.extend(sans_ips)
    settings = {
        'sans': json.dumps(sans),
        'common_name': cn,
        'certificate_name': cn
    }
    log("TLS_CTX: {}".format(settings))
    return settings


def tls_changed(module, rel_data):
    if not rel_data:
        # departed case
        cert = key = ca = None
    else:
        # changed case
        unitname = local_unit().replace('/', '_')
        cert_name = '{0}.server.cert'.format(unitname)
        key_name = '{0}.server.key'.format(unitname)
        cert = rel_data.get(cert_name)
        key = rel_data.get(key_name)
        ca = rel_data.get('ca')
        if not cert or not key or not ca:
            log("tls-certificates client's relation data is not fully available. Rel data: {}".format(rel_data))
            cert = key = ca = None

    changed = update_certificates(module, cert, key, ca)
    if not changed:
        log("Certificates were not changed.")
        return False

    log("Certificates have been changed. Rewrite configs and rerun services.")
    if cert is not None and len(cert) > 0:
        config["ssl_enabled"] = True
        config["ca_cert"] = ca
    else:
        config["ssl_enabled"] = False
        config.pop("ca_cert", None)
    config.save()
    return True


def _try_os(func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except Exception:
        pass


def update_certificates(module, cert, key, ca):
    certs_path = "/etc/contrail/ssl/{}".format(module)
    files = {"/certs/server.pem": (cert, 0o644),
             "/private/server-privkey.pem": (key, 0o640),
             "/certs/ca-cert.pem": (ca, 0o644)}
    # create common directories to create symlink
    # this is needed for contrail-status
    _try_os(os.makedirs, "/etc/contrail/ssl/certs")
    _try_os(os.makedirs, "/etc/contrail/ssl/private")
    changed = False
    for fkey in files:
        cfile = certs_path + fkey
        data = files[fkey][0]
        old_hash = file_hash(cfile)
        save_file(cfile, data, perms=files[fkey][1])
        changed |= (old_hash != file_hash(cfile))
        # create symlink to common place
        _try_os(os.remove, "/etc/contrail/ssl" + fkey)
        _try_os(os.symlink, cfile, "/etc/contrail/ssl" + fkey)
    # apply strange permissions to certs to allow containers to read them
    # group 1011 is a hardcoded group id for internal contrail purposes
    if os.path.exists(certs_path + "/certs"):
        os.chmod(certs_path + "/certs", 0o755)
    if os.path.exists(certs_path + "/private"):
        os.chmod(certs_path + "/private", 0o750)
        os.chown(certs_path + "/private", 0, 1011)
    if key:
        os.chown(certs_path + "/private/server-privkey.pem", 0, 1011)

    return changed


def render_and_log(template, conf_file, ctx, perms=0o600):
    """Returns True if configuration has been changed."""

    log("Render and store new configuration: " + conf_file)
    try:
        with open(conf_file) as f:
            old_lines = set(f.readlines())
    except Exception:
        old_lines = set()

    render(template, conf_file, ctx, perms=perms)
    with open(conf_file) as f:
        new_lines = set(f.readlines())
    new_set = new_lines.difference(old_lines)
    old_set = old_lines.difference(new_lines)
    if not new_set and not old_set:
        log("Configuration file has not been changed.")
    elif not old_lines:
        log("Configuration file has been created and is not logged.")
    else:
        log("New lines set:\n{new}".format(new="".join(new_set)))
        log("Old lines set:\n{old}".format(old="".join(old_set)))
        log("Configuration file has been changed.")

    return bool(new_set or old_set)


def rsync_nrpe_checks(plugins_dir):
    if not os.path.exists(plugins_dir):
        os.makedirs(plugins_dir)

    charm_plugin_dir = os.path.join(charm_dir(),
                                    'files',
                                    'plugins/')
    rsync(charm_plugin_dir,
          plugins_dir,
          options=['--executability'])


def add_nagios_to_sudoers():
    sudoers_content = 'nagios ALL = NOPASSWD: /usr/bin/contrail-status'
    cmd = ('sudo bash -c \'echo \"{}\" > /etc/sudoers.d/nagios\''
           .format(sudoers_content))
    try:
        check_call(cmd, shell=True)
    except CalledProcessError as err:
        log('Failed to run cmd: {}'.format(err.cmd))


def contrail_status_cmd(name, plugins_dir):
    script_name = 'check_contrail_status_{}.py'.format(name)
    tag = config.get('image-tag')
    cver = '5.1'
    if '5.0' in tag:
        cver = '5.0'

    check_contrail_status_script = os.path.join(
        plugins_dir,
        script_name
        )
    check_contrail_status_cmd = (
        '{} {}'
        .format(check_contrail_status_script, cver)
    )
    return check_contrail_status_cmd


def is_config_analytics_ssl_available():
    tag = config.get("image-tag")
    # for now image tags are looking as YYMMsomethingelse, if the format
    # changes, this logic needs to be rewrited
    if '5.0' in tag or '5.1' in tag:
        return False

    tag_date = re.findall(r"19\d\d", tag)
    if len(tag_date) == 0:
        tag_date = re.findall(r"20\d\d", tag)
    if len(tag_date) != 0:
        ver = int(tag_date[0])
        tag = 'latest' if ver >= 1910 else ''

    if 'latest' in tag or 'master' in tag:
        return True

    return False
