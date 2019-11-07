#!/usr/bin/env python3

import subprocess
import sys

SERVICES = {
    'control': [
        'control',
        'nodemgr',
        'named',
        'dns',
    ],
    'config-database': [
        'nodemgr',
        'zookeeper',
        'rabbitmq',
        'cassandra',
    ],
    'webui': [
        'web',
        'job',
    ],
    'config': [
        'svc-monitor',
        'nodemgr',
        'device-manager',
        'api',
        'schema',
    ],
}

WARNING = 1
CRITICAL = 2


def check_contrail_status(services):

    try:
        output = subprocess.check_output("export CONTRAIL_STATUS_CONTAINER_NAME=contrail-status-controller-nrpe ; sudo -E contrail-status", shell=True).decode('UTF-8')
    except subprocess.CalledProcessError as err:
        message = ('CRITICAL: Could not get contrail-status.'
                   ' return code: {} cmd: {} output: {}'.
                   format(err.returncode, err.cmd, err.output))
        print(message)
        sys.exit(CRITICAL)

    statuses = dict()
    group = None
    for line in output.splitlines()[1:]:
        words = line.split()
        if len(words) == 4 and words[0] == '==' and words[3] == '==':
            group = words[2]
            continue
        if len(words) == 0:
            group = None
            continue
        if group and len(words) >= 2 and group in services:
            srv = words[0].split(':')[0]
            statuses.setdefault(group, dict())[srv] = (
                words[1], ' '.join(words[2:]))

    for group in services:
        if group not in statuses:
            message = ('WARNING: POD {} is absent in the contrail-status'
                       .format(group))
            print(message)
            sys.exit(WARNING)
        for srv in services[group]:
            if srv not in statuses[group]:
                message = ('WARNING: {} is absent in the contrail-status'
                           .format(srv))
                print(message)
                sys.exit(WARNING)
            status, desc = statuses[group].get(srv)
            if status not in ['active', 'backup']:
                message = ('CRITICAL: {} is not ready. Reason: {}'
                           .format(srv, desc if desc else status))
                print(message)
                sys.exit(CRITICAL)
    print('Contrail status OK')
    sys.exit()


if __name__ == '__main__':
    check_contrail_status(SERVICES)
