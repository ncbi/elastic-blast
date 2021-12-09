#!/usr/bin/env python3
"""
lambda_elb.py - Lambda function to invoke the ElasticBLAST janitor module

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
Created: Mon 13 Sep 2021 09:26:56 AM EDT
"""
import os, json, logging, elastic_blast
from pprint import pformat
from elastic_blast.aws import ElasticBlastAws
from elastic_blast.janitor import janitor
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.util import UserReportError, SafeExecError
from elastic_blast.filehelper import open_for_read
from elastic_blast.constants import ElbCommand, ELB_META_CONFIG_FILE, ELB_METADATA_DIR

# From https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html#configuration-envvars-runtime
AWS_LAMBDA_ENV_VARS = [
  '_HANDLER',
  '_X_AMZN_TRACE_ID',
  'AWS_REGION',
  'AWS_EXECUTION_ENV',
  'AWS_LAMBDA_FUNCTION_NAME',
  'AWS_LAMBDA_FUNCTION_MEMORY_SIZE',
  'AWS_LAMBDA_FUNCTION_VERSION',
  'AWS_LAMBDA_INITIALIZATION_TYPE',
  'AWS_LAMBDA_LOG_GROUP_NAME',
  'AWS_LAMBDA_LOG_STREAM_NAME',
  'AWS_ACCESS_KEY_ID',
  'AWS_SECRET_ACCESS_KEY',
  'AWS_SESSION_TOKEN',
  'AWS_LAMBDA_RUNTIME_API',
  'LAMBDA_TASK_ROOT',
  'LAMBDA_RUNTIME_DIR',
  'TZ'
]

def print_lambda_env_vars():
  for ev in AWS_LAMBDA_ENV_VARS:
      if ev in os.environ:
          logging.debug(f"{ev}={os.environ[ev]}")

def print_lambda_context(context):
    if not context: return
    logging.debug(f"Lambda function ARN: {context.invoked_function_arn}")
    logging.debug(f"CloudWatch log stream name: {context.log_stream_name}")
    logging.debug(f"CloudWatch log group name:  {context.log_group_name}")
    logging.debug(f"Lambda Request ID: {context.aws_request_id}")
    logging.debug(f"Lambda function memory limits in MB: {context.memory_limit_in_mb}")

def print_elastic_blast_info():
    logging.debug(f'ElasticBLAST version {elastic_blast.VERSION}')
    logging.debug(f'ElasticBLAST GCP Query Splitting docker image {elastic_blast.constants.ELB_QS_DOCKER_IMAGE_GCP}')
    logging.debug(f'ElasticBLAST AWS Query Splitting docker image {elastic_blast.constants.ELB_QS_DOCKER_IMAGE_AWS}')
    logging.debug(f'ElasticBLAST GCP Job Submitting docker image {elastic_blast.constants.ELB_CJS_DOCKER_IMAGE_GCP}')
    logging.debug(f'ElasticBLAST AWS Job Submitting docker image {elastic_blast.constants.ELB_CJS_DOCKER_IMAGE_AWS}')
    logging.debug(f'ElasticBLAST GCP BLAST docker image {elastic_blast.constants.ELB_DOCKER_IMAGE_GCP}')
    logging.debug(f'ElasticBLAST AWS BLAST docker image {elastic_blast.constants.ELB_DOCKER_IMAGE_AWS}')


def config_logging():
    #handler = logging.StreamHandler()
    #handler.setLevel(logging.DEBUG)
    #logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG)
    for _ in ['boto3', 'botocore', 'urllib3', 's3transfer']:
        logging.getLogger(_).setLevel(logging.CRITICAL)


def handler(event, context):
    logging.debug(f'Received event: {json.dumps(event)}')
    config_logging()
    print_elastic_blast_info()
    try:
        print_lambda_env_vars()
        print_lambda_context(context)
        if 'ELB_RESULTS' in event:
            os.environ['ELB_RESULTS'] = event['ELB_RESULTS']
        else:
            raise RuntimeError(f'FATAL ERROR: Missing parameter ELB_RESULTS')

        cfg_uri = os.path.join(os.environ['ELB_RESULTS'], ELB_METADATA_DIR, ELB_META_CONFIG_FILE)
        logging.debug(f"Loading {cfg_uri}")
        with open_for_read(cfg_uri) as f:
            cfg_json = f.read()
        cfg = ElasticBlastConfig.from_json(cfg_json)
        logging.debug(f'{cfg.to_json()}')
        cfg.validate(ElbCommand.STATUS)

        eb = ElasticBlastAws(cfg, False)
        if 'ELB_DRY_RUN' in event:    # for debugging
            eb.dry_run = True
        janitor(eb)
    except (SafeExecError, UserReportError) as e:
        logging.error(e.message)
        if isinstance(e, SafeExecError):
            msg = f'The command {e.cmd} returned with exit code {e.returncode}'
            if e.stdout is not None and len(e.stdout.decode()):
                msg += f' - stdout={e.stdout.decode()}'
            if e.stderr is not None and len(e.stderr.decode()):
                msg += f' - stderr={e.stderr.decode()}'
            raise RuntimeError(msg)
    return 'SUCCESS'

if __name__ == "__main__":
    import sys, traceback
    try:
        # For testing, convert environment variables into events
        events = {}
        if 'ELB_RESULTS' in os.environ:
            events['ELB_RESULTS'] = os.environ['ELB_RESULTS']
        else:
            raise RuntimeError(f'FATAL ERROR: Missing parameter ELB_RESULTS')
        if 'ELB_DRY_RUN' in os.environ:
            events['ELB_DRY_RUN'] = '1'
        handler(events, None)
    except Exception as e:
        print(e, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

