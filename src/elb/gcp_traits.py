#                           PUBLIC DOMAIN NOTICE
#              National Center for Biotechnology Information
#  
# This software is a "United States Government Work" under the
# terms of the United States Copyright Act.  It was written as part of
# the authors' official duties as United States Government employees and
# thus cannot be copyrighted.  This software is freely available
# to the public for use.  The National Library of Medicine and the U.S.
# Government have not placed any restriction on its use or reproduction.
#   
# Although all reasonable efforts have been taken to ensure the accuracy
# and reliability of the software and data, the NLM and the U.S.
# Government do not and cannot warrant the performance or results that
# may be obtained by using this software or data.  The NLM and the U.S.
# Government disclaim all warranties, express or implied, including
# warranties of performance, merchantability or fitness for any particular
# purpose.
#   
# Please cite NCBI in any work or product based on this material.

"""
elb/gcp_traits.py - helper module for GCP machine info

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import re
from .base import InstanceProperties

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
