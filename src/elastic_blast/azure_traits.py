# for azure

"""
elb/gcp_traits.py - helper module for GCP machine info

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import re, logging
import subprocess
import json
from typing import List
from .base import InstanceProperties
from .util import UserReportError, safe_exec
from .constants import DEPENDENCY_ERROR, GCP_APIS
from datetime import datetime, timedelta, timezone
from azure.identity import ClientSecretCredential # type: ignore
from azure.storage.blob import (BlobServiceClient, generate_account_sas, generate_container_sas, AccountSasPermissions, ContainerSasPermissions, ResourceTypes)  # type: ignore

AZURE_HPC_MACHINES = {
    'Standard_HB120rs_v3': {'cpu': 120, 'memory': 480},  # 120 vCPU, 480 GB RAM
    'Standard_HC44rs': {'cpu': 44, 'memory': 352},  # 44 vCPU, 352 GB RAM
    'Standard_HB60rs': {'cpu': 60, 'memory': 240},  # 60 vCPU, 240 GB RAM
    'Standard_D16s_v3': {'cpu': 16, 'memory': 64},  # 16 vCPU, 64 GB RAM
    'Standard_D32s_v3': {'cpu': 32, 'memory': 128},  # 32 vCPU, 128 GB RAM
    'Standard_D64s_v3': {'cpu': 64, 'memory': 256},  # 64 vCPU, 256 GB RAM
    'Standard_E16s_v3': {'cpu': 16, 'memory': 128},  # 16 vCPU, 128 GB RAM
    'Standard_E32s_v3': {'cpu': 32, 'memory': 256},  # 32 vCPU, 256 GB RAM
    'Standard_E64s_v3': {'cpu': 64, 'memory': 432},  # 64 vCPU, 432 GB RAM
    'Standard_E64is_v3': {'cpu': 64, 'memory': 504},  # 64 vCPU, 504 GB RAM
    'Standard_D8s_v3': {'cpu': 8, 'memory': 32},  # 8 vCPU, 32 GB RAM

}

MIN_PROCESSORS = 8
MIN_MEMORY = 24 # GB

def get_azure_blob_client(account_url: str, tenant_id:str, client_id: str, client_secret: str) -> BlobServiceClient:
    """ Create Azure Blob Service Client """
    credential = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
    return BlobServiceClient(account_url=account_url, credential=credential)

def get_sas_token(storage_account: str, storage_account_container: str, storage_account_key: str) -> str:
    """ Get SAS token for Azure Blob Storage """
    try:
        return generate_account_sas(
            account_key=storage_account_key,
            account_name=storage_account,
            resource_types=ResourceTypes(container=True, object=True),
            # container_name=storage_account_container,
            permission=AccountSasPermissions(read=True, write=True, delete=True, create=True, add=True, list=True),
            start=datetime.now(timezone.utc) - timedelta(hours=1), # allow 1 hour back
            expiry=datetime.now(timezone.utc) + timedelta(hours=8)
        )
    except Exception as e:
        logging.error(f'Error generating SAS token: {e}')
    return ''
    
def get_latest_dir(storage_account: str, storage_account_container: str, storage_account_key: str) -> str:
    """ Get the latest directory from Azure Blob Storage """
    connection_string = f"DefaultEndpointsProtocol=https;AccountName={storage_account};AccountKey={storage_account_key};EndpointSuffix=core.windows.net"
    client = BlobServiceClient.from_connection_string(connection_string)
    container = client.get_container_client(storage_account_container)
    
    # get all folders
    folder_list = []
    for blob in container.walk_blobs(name_starts_with='/'):
        if blob.name.endswith('/'):
            folder_list.append(blob.name[:-1]) # remove trailing slash and add to list
        
    # get the latest folder
    latest_dir = ''
    latest_time = datetime.min.replace(tzinfo=timezone.utc)
    for blob in container.list_blobs():
        if blob.name in folder_list:
            if blob.last_modified > latest_time:
                latest_time = blob.last_modified
                latest_dir = blob.name
    return latest_dir
    
    

def get_machine_properties(machineType: str) -> InstanceProperties:
    """Given the Azure VM size, returns a tuple of number of CPUs and amount of RAM in GB."""
    if machineType in AZURE_HPC_MACHINES:
        properties = AZURE_HPC_MACHINES[machineType]
        ncpu = properties['cpu']
        nram = properties['memory']
    else:
        err = f'Cannot get properties for {machineType}'
        raise NotImplementedError(err)
    
    return InstanceProperties(ncpu, nram)

def get_instance_type_offerings(region: str) -> List[any]:
    """Get a list of instance types offered in an Azure region"""
    try:
        cmd = f'az vm list-sizes --location {region} --query "[?numberOfCores >= \`{MIN_PROCESSORS}\` && memoryInMB >= \`{MIN_MEMORY*1024}\`]" -o json'
        result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        vm_list = json.loads(result.stdout)
        
        if not vm_list:
            raise ValueError(f"VM size '{vm_list}' not found in location '{region}'")
        
        # return [vm['name'] for vm in vm_list]
        return vm_list
        
    except subprocess.CalledProcessError as e:
        logging.error(f'Error getting instance types in region {region}: {e.stderr}')
        raise UserReportError(returncode=DEPENDENCY_ERROR, message=f'Error getting instance types in region {region}')
    


