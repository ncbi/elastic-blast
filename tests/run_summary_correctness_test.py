#!/usr/bin/env python3
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

import os, sys, re, json, argparse
from datetime import datetime
from pathlib import Path


def validTime(dt):
    try:
        d = datetime.fromisoformat(dt)
        return True
    except ValueError:
        return False


def isNumber(n):
    return type(n) == int or type(n) == float

# GCP machine info
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
def getMachineProperties(machineType):
    ncpu = 0
    nram = 0
    mo = re_gcp_machine_type.match(machineType)
    if mo:
        series, sncpu = mo.groups()
        ncpu = int(sncpu)
        nram = ncpu * GCP_MACHINES[series]
    return ncpu, nram

# This is a sample structure to check JSON response against
# Where leafs are of specific types, int, str, or float they
# are checked literally for exact match. If the type is a function
# it is supposed to be a function of one argument returning True
# if the match is successful. If the type is type, it is tested
# that concrete leaf (of the JSON checked) is of this type.
machineType = os.getenv('ELB_MACHINE_TYPE', "n1-standard-32")
ncpu, nram = getMachineProperties(machineType)
sample = {
  "version": "1.0",
  "clusterInfo": {
    "provider": "GCP",
    "numMachines": int(os.getenv('ELB_NUM_NODES', '1')),
    "numVCPUsPerMachine": ncpu,
    "RamPerMachine": nram,
    "machine-name": machineType,
    "region": "us-east4",
    "zone": "us-east4-b",
    "storageType": "persistentDisk"
  },
  "runtime": {
    "wallClock": isNumber,
    "blastdbSetup": {
      "startTime": validTime,
      "endTime": validTime
    },
    "blast": {
      "startTime": validTime,
      "endTime": validTime
    }
  },
  "blastData": {
    "queryLength": lambda x: type(x) == int and x > 0,
    "databaseLength": lambda x: type(x) == int and x > 0
  },
  "bases_per_second_per_cpu": isNumber,
  "exitCode": 0
}


def dfsWalk(obj, visit, path=[]):
    if type(obj) == dict:
        for key, value in obj.items():
            dfsWalk(value, visit, path + [key])
    elif type(obj) == list:
        for idx, value in enumerate(obj):
            dfsWalk(value, visit, path + [idx])
    else:
        visit(path, obj)


def getItem(container, *path):
    d = container
    for part in path:
        d1 = d.get(part)
        if d1 is None:
            return None
        d = d1
    return d


function = type(lambda:0)
def compare(sample, obj):
    if type(sample) == type:
        return type(obj) == sample
    elif type(sample) == function:
        return sample(obj)
    else:
        return sample == obj


def main():
    parser = argparse.ArgumentParser(description="Application to test run-summary output")
    parser.add_argument("run_summary", type=argparse.FileType('r'), help="Run-summary JSON file")
    args = parser.parse_args()
    if Path(args.run_summary.name).stat().st_size == 0:
        raise RuntimeError(f'{args.run_summary.name} is empty')
    summary = json.load(args.run_summary)
    results = []
    def accCompare(path, value):
        results.append(compare(value, getItem(summary, *path)))
    dfsWalk(sample, accCompare)
    for ind, value in enumerate(results):
        if not value:
            # Log detailed diagnostics if something doesn't check
            dfsWalk(sample, lambda path, value: print(path, '-', value, getItem(summary, *path), compare(value, getItem(summary, *path))))
            return ind+1
    return 0


if __name__ == '__main__':
    sys.exit(main())
