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
elastic_blast/object_storage_utils.py - utility module to deal with object storage

"""

from botocore.config import Config  # type: ignore
from botocore.exceptions import ClientError # type: ignore
import boto3 # type: ignore
import logging
import os
import errno
from pathlib import Path
from .filehelper import parse_bucket_name_key


def write_to_s3(dest: str, contents: str, boto_cfg: Config = None, dry_run: bool = False) -> None:
    """ Writes its second argument as an object specified by this function's first argument.
        dest: string containing an AWS S3 bucket object name
        contents: what to write into said S3 object
        boto_cfg: boto3 library configuration
        dry_run: if True, does nothing
    """
    if dry_run: 
        logging.debug(f'Would have written "{contents}" to {dest}')
        return
    s3 = boto3.resource('s3') if boto_cfg == None else boto3.resource('s3', config=boto_cfg)
    bucket_name, key = parse_bucket_name_key(dest)
    bucket = s3.Bucket(bucket_name)
    bucket.put_object(Body=contents.encode(), Key=key)
    logging.debug(f'Uploaded {dest}')
    return


def copy_file_to_s3(dest: str, file_object: Path, boto_cfg: Config = None, dry_run: bool = False) -> None:
    """ Writes its second argument as an object specified by this function's first argument.
        dest: string containing an AWS S3 bucket object name
        file_object: file to copy to S3
        boto_cfg: boto3 library configuration
        dry_run: if True, does nothing
    """
    if dry_run: 
        logging.debug(f'Would have copied "{file_object.resolve()}" to {dest}')
        return
    s3 = boto3.resource('s3') if boto_cfg == None else boto3.resource('s3', config=boto_cfg)
    bucket_name, key = parse_bucket_name_key(dest)
    bucket = s3.Bucket(bucket_name)
    bucket.upload_file(Filename=str(file_object.resolve()), Key=key)
    return


def delete_from_s3(object_name: str, boto_cfg: Config = None, dry_run: bool = False) -> None:
    """ Delete the object specified via this function's first argument 

        object_name: string containing an AWS S3 bucket object name
        boto_cfg: boto3 library configuration
        dry_run: if True, does nothing
    """
    bname, prefix = parse_bucket_name_key(object_name)
    if dry_run:
        logging.debug(f'dry-run: would have removed {bname}/{prefix}')
        return

    s3 = boto3.resource('s3') if boto_cfg == None else boto3.resource('s3', config=boto_cfg)
    s3_bucket = s3.Bucket(bname)
    s3_bucket.objects.filter(Prefix=prefix).delete()
    return


def download_from_s3(object_name: str, local_file: Path, boto_cfg: Config = None, dry_run: bool = False) -> None:
    """ Downloads a file from AWS S3 identified by the first argument and saves
    it to the local file specified by its second argument. 
    Raises FileNotFoundError if the object_name does not exist
    """

    if dry_run: 
        logging.debug(f'Would have saved "{object_name}" to "{str(local_file)}"')
        return
    s3 = boto3.resource('s3') if boto_cfg == None else boto3.resource('s3', config=boto_cfg)
    bname, prefix = parse_bucket_name_key(object_name)
    # https://boto3.amazonaws.com/v1/documentation/api/1.9.42/guide/s3-example-download-file.html
    try:
        s3.Bucket(bname).download_file(prefix, str(local_file))
        logging.debug(f'Downloaded {object_name} to {str(local_file)}')
    except ClientError as e:
        if e.response['Error']['Code'] == "404":
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), object_name)
        else:
            raise

