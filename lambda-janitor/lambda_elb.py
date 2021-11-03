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
from elastic_blast.filehelper import thaw_config
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.util import UserReportError, SafeExecError
from elastic_blast.constants import ElbCommand

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
          print(f"{ev}={os.environ[ev]}")

def print_lambda_context(context):
    if not context: return
    print("Lambda function ARN:", context.invoked_function_arn)
    print("CloudWatch log stream name:", context.log_stream_name)
    print("CloudWatch log group name:",  context.log_group_name)
    print("Lambda Request ID:", context.aws_request_id)
    print("Lambda function memory limits in MB:", context.memory_limit_in_mb)

def print_elastic_blast_info():
    print(f'ElasticBLAST version {elastic_blast.VERSION}')
    print(f'ElasticBLAST GCP Query Splitting docker image {elastic_blast.constants.ELB_QS_DOCKER_IMAGE_GCP}')
    print(f'ElasticBLAST AWS Query Splitting docker image {elastic_blast.constants.ELB_QS_DOCKER_IMAGE_AWS}')
    print(f'ElasticBLAST GCP BLAST docker image {elastic_blast.constants.ELB_DOCKER_IMAGE_GCP}')
    print(f'ElasticBLAST AWS BLAST docker image {elastic_blast.constants.ELB_DOCKER_IMAGE_AWS}')

def config_logging():
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    logging.getLogger('').addHandler(handler)

def handler(event, context):
    print(f'Received event: {json.dumps(event)}')
    config_logging()
    print_elastic_blast_info()
    try:
      print_lambda_env_vars()
      print_lambda_context(context)
      for ev in ('ELB_RESULTS', 'ELB_CLUSTER_NAME'):
        if ev in event:
            os.environ[ev] = event[ev]
        else:
            raise RuntimeError(f'FATAL ERROR: Missing parameter {ev}')

      cf = thaw_config(event['ELB_RESULTS'])
      logging.debug(f'Thawed config {pformat(cf)}')
      logging.debug(f'PROGRAM {cf["blast"]["program"]}')
      logging.debug(f'BLASTDB {cf["blast"]["db"]}')
      logging.debug(f'QUERY {cf["blast"]["queries_arg"]}')
      cfg = ElasticBlastConfig(aws_region = os.environ['AWS_REGION'],
                               program = cf['blast']['program'],
                               db = cf['blast']['db'],
                               queries = cf['blast']['queries_arg'],
                               results = event['ELB_RESULTS'],
                               cluster_name = event['ELB_CLUSTER_NAME'],
                               task = ElbCommand.STATUS)
      cfg.validate(ElbCommand.STATUS)
      logging.debug(f'{pformat(cfg.asdict())}')

      logging.debug(f'Before initialzation of ElasticBlastAws')
      eb = ElasticBlastAws(cfg)
      logging.debug(f'After initialzation of ElasticBlastAws')
      if 'ELB_DRY_RUN' in event:    # for debugging
        eb.dry_run = True
      logging.debug(f'About to call elastic_blast.janitor.janitor')
      janitor(eb)
    except (SafeExecError, UserReportError) as e:
        print(e.message)
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
        for ev in ('ELB_RESULTS', 'ELB_CLUSTER_NAME'):
            if ev in os.environ:
                events[ev] = os.environ[ev]
            else:
                raise RuntimeError(f'FATAL ERROR: Missing parameter {ev}')
        if 'ELB_DRY_RUN' in os.environ:
            events['ELB_DRY_RUN'] = '1'
        handler(events, None)
    except Exception as e:
        print(e, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

