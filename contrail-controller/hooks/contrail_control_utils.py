import functools
import os
import pwd
import shutil
from socket import gethostbyname, gethostname
from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
from time import sleep, time

import apt_pkg
import yaml

try:
  import netaddr
  import netifaces
except ImportError:
  pass

from charmhelpers.core.hookenv import (
    config,
    log,
    related_units,
    relation_get,
    relation_ids,
    relation_type,
    remote_unit
)

from charmhelpers.core.host import service_restart, service_start

from charmhelpers.core.templating import render

apt_pkg.init()


config = config()

def retry(f=None, timeout=10, delay=2):
    """Retry decorator.

    Provides a decorator that can be used to retry a function if it raises
    an exception.

    :param timeout: timeout in seconds (default 10)
    :param delay: retry delay in seconds (default 2)

    Examples::

        # retry fetch_url function
        @retry
        def fetch_url():
            # fetch url

        # retry fetch_url function for 60 secs
        @retry(timeout=60)
        def fetch_url():
            # fetch url
    """
    if not f:
        return functools.partial(retry, timeout=timeout, delay=delay)
    @functools.wraps(f)
    def func(*args, **kwargs):
        start = time()
        error = None
        while True:
            try:
                return f(*args, **kwargs)
            except Exception as e:
                error = e
            elapsed = time() - start
            if elapsed >= timeout:
                raise error
            remaining = timeout - elapsed
            if delay <= remaining:
                sleep(delay)
            else:
                sleep(remaining)
                raise error
    return func

def contrail_api_ctx():
    ip = config.get("contrail-api-ip")
    if ip:
        port = config.get("contrail-api-port")
        return { "api_server": ip,
                 "api_port": port if port is not None else 8082 }

    ctxs = [ { "api_server": gethostbyname(relation_get("private-address", unit, rid)),
               "api_port": port }
             for rid in relation_ids("contrail-api")
             for unit, port in
             ((unit, relation_get("port", unit, rid)) for unit in related_units(rid))
             if port ]
    return ctxs[0] if ctxs else {}

def contrail_discovery_ctx():
    ip = config.get("discovery-server-ip")
    if ip:
        return { "discovery_server": ip,
                 "discovery_port": 5998 }

    ctxs = [ { "discovery_server": vip if vip \
                 else gethostbyname(relation_get("private-address", unit, rid)),
               "discovery_port": port }
             for rid in relation_ids("contrail-discovery")
             for unit, port, vip in
             ((unit, relation_get("port", unit, rid), relation_get("vip", unit, rid))
              for unit in related_units(rid))
             if port ]
    return ctxs[0] if ctxs else {}

def identity_admin_ctx():
    ctxs = [ { "auth_host": gethostbyname(hostname),
               "auth_port": relation_get("service_port", unit, rid),
               "admin_user": relation_get("service_username", unit, rid),
               "admin_password": relation_get("service_password", unit, rid),
               "admin_tenant_name": relation_get("service_tenant_name", unit, rid),
               "auth_region": relation_get("service_region", unit, rid) }
             for rid in relation_ids("identity-admin")
             for unit, hostname in
             ((unit, relation_get("service_hostname", unit, rid)) for unit in related_units(rid))
             if hostname ]
    return ctxs[0] if ctxs else {}
