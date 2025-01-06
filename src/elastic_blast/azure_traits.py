# for azure

"""
elb/gcp_traits.py - helper module for GCP machine info

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import re, logging
from .base import InstanceProperties
from .util import safe_exec
from .constants import GCP_APIS

GCP_MACHINES = {
    "n1-standard" : 3.75,
    "n1-highmem"  : 6.5,
    "n1-highcpu"  : 0.9,
    "n2-standard" : 4,
    "n2-highmem"  : 8,
    "n2-highcpu"  : 1,
    "n2d-standard" : 4,
    "n2d-highmem"  : 8,
    "n2d-highcpu"  : 1,
    "e2-standard" : 4,
    "e2-highmem"  : 8,
    "e2-highcpu"  : 1,
    "m1-ultramem" : 24.025,
    "m1-megamem"  : 14.93333,
    "m2-ultramem" : 28.307692307692308,
    "c2-standard" : 4,
}
re_gcp_machine_type = re.compile(r'([^-]+-[^-]+)-([0-9]+)')
def get_machine_properties(machineType: str) -> InstanceProperties:
    raise NotImplementedError('Azure API enabling is not implemented')
    """ given the CGP machine type returns tuple of number of CPUs and abount of RAM in GB """
    ncpu = 0
    nram = 0.0
    mo = re_gcp_machine_type.match(machineType)
    if mo:
        series, sncpu = mo.groups()
        ncpu = int(sncpu)
        nram = ncpu * GCP_MACHINES[series]
    else:
        # Should not return 0 CPUs or RAM
        err = f'Cannot get properties for {machineType}'
        raise NotImplementedError(err)
    return InstanceProperties(ncpu, nram)


def enable_azure_api(project: str, dry_run: bool):
    raise NotImplementedError('Azure API enabling is not implemented')

    """ Enable GCP APIs if they are not already enabled
    parameters:
        project: GCP project
        dry_run: True for dry run
    raises:
        SafeExecError if there is an error checking or trying to enable APIs
    """
    for api in GCP_APIS:
        cmd = 'gcloud services list --enabled --format=value(config.name) '
        cmd += f'--filter=config.name={api}.googleapis.com '
        cmd += f'--project {project}'
        if dry_run:
            logging.info(cmd)
        else:
            p = safe_exec(cmd)
            if not p.stdout:
                cmd = f'gcloud services enable {api}.googleapis.com '
                cmd += f'--project {project}'
                p = safe_exec(cmd)
