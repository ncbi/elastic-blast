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
elb/comands/run_summary.py - generate run summary

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import sys
import time
import math
import logging
import os
import json
import re
import argparse
from dataclasses import dataclass, field
from typing import List
import boto3  # type: ignore
from botocore.exceptions import ClientError  #type: ignore
from elastic_blast.aws_traits import create_aws_config
from elastic_blast.aws import handle_aws_error
from elastic_blast.util import safe_exec
from elastic_blast.filehelper import parse_bucket_name_key
from elastic_blast.constants import ELB_AWS_JOB_IDS, ELB_AWS_QUERY_LENGTH, ELB_METADATA_DIR
from elastic_blast.constants import ELB_LOG_DIR, CSP, ElbCommand

# Artificial exit codes to differentiate failure modes
# of AWS job.
JOB_EXIT_CODE_UNINITIALIZED = -1
JOB_EXIT_CODE_FAILED_WITH_NO_ATTEMPT = 100000
JOB_EXIT_CODE_FAILED_WITH_NO_EXIT_CODE = 100001

# Phases of AWS job
PHASE_BLASTDB_SETUP = 'blastDbSetup'
PHASE_BLAST = 'blast'
PHASE_QUERY_DOWNLOAD = 'queryDownload'
PHASE_QUERY_SPLIT = 'querySplit'


@dataclass
class Run:
    njobs: int = 0
    start_time: int = 0
    end_time:  int = 0
    exit_codes: List[int] = field(default_factory=list)
    phase_names: List[str] = field(default_factory=list)
    def read_log_parser(self, log_parser):
        # Copy all run phases
        for _, _, phase in run_phases:
            vars = [
                phase + '_time',
                phase + '_num',
                phase + '_min',
                phase + '_max'
            ]
            var_present = False
            for var in vars:
                if hasattr(log_parser, var):
                    setattr(self, var, getattr(log_parser, var))
                    var_present = True
            if var_present:
                self.phase_names.append(phase)

        vars = [ 'db_num_seq', 'db_length', 'query_length', 'cluster_name',
                 'instance_type', 'instance_vcpus', 'instance_ram', 'min_vcpus',
                 'max_vcpus', 'num_nodes']
        for var in vars:
            if hasattr(log_parser, var):
                setattr(self, var, getattr(log_parser, var))

def create_arg_parser(subparser, common_opts_parser):
    """ Create the command line options subparser for the command. """
    parser = subparser.add_parser('run-summary',
            help='ElasticBLAST run summary generation tool',
            parents=[common_opts_parser])
    parser.add_argument('-o', '--output', type=argparse.FileType('wt'), default='-', 
            help='Output file, default: stdout')
    parser.add_argument('-d', '--detailed', action="store_true", default=False,
        help='List log files consulted for info')
    parser.add_argument('-l', '--write-logs', type=argparse.FileType('wt'), default=None,
        help='File name to write log files to')
    parser.add_argument('-r', '--read-logs', type=argparse.FileType('rt'), default=None,
        help='File name to read log files from')

#    parser.add_argument("--run-label", type=str,
#            help="Run-label to use for this ElasticBLAST search, format: key:value")
    parser.set_defaults(func=_run_summary)


def _run_summary(args, cfg, clean_up_stack):
    """ Entry point to delete resources associated with an ElasticBLAST search """
    cfg.validate(ElbCommand.RUN_SUMMARY)
    cloud_provider = cfg.cloud_provider.cloud
    if cloud_provider == CSP.AWS:
        if args.read_logs:
            run = _read_job_logs_aws_from_file(args.read_logs)
        else:
            run = _read_job_logs_aws(cfg, args.write_logs)
    elif cloud_provider == CSP.GCP:
        run = _read_job_logs_gcp(cfg)
    else:
        raise NotImplementedError(f'run-summary sub-command is not implemented for {cloud_provider.name}')
    nnotdone = sum(map(lambda x: 1 if x < 0 else 0, run.exit_codes))
    if nnotdone:
        print(f'{nnotdone} jobs still pending', file=sys.stderr)
        return 0
    nfailed = sum(map(lambda x: 1 if x > 0 else 0, run.exit_codes))
    now = _format_time(time.time())

#    logging.debug(f'{_format_time(start_time)} START blast')
#    logging.debug(f'{_format_time(end_time)} END blast')
#    logging.debug(f'JOBS blast {njobs} done, {nfailed} failed')
#    logging.debug(f'RUNTIME blast {end_time-start_time:.3f} seconds')
    summary = {}
    summary['version'] = "1.0"  # FIXME: should this match elastic_blast.version?
    summary['clusterInfo'] = {}
    summary['clusterInfo']['provider'] = cloud_provider.name
    if hasattr(run, 'num_nodes'):
        summary['clusterInfo']['numMachines'] = run.num_nodes
    else:
        summary['clusterInfo']['numMachines'] = cfg.cluster.num_nodes
    if hasattr(run, 'instance_type'):
        machineType = run.instance_type
    else:
        machineType = cfg.cluster.machine_type
    if hasattr(run, 'cluster_name'):
        summary['clusterInfo']['name'] = run.cluster_name
    if hasattr(run, 'instance_vcpus'):
        summary['clusterInfo']['numVCPUsPerMachine'] = run.instance_vcpus
    if hasattr(run, 'instance_ram'):
        summary['clusterInfo']['RamPerMachine'] = run.instance_ram
    summary['clusterInfo']['machineType'] = machineType
#    summary['clusterInfo']['region'] = run.getInfoItem('init', 'region')
#    summary['clusterInfo']['zone'] = run.getInfoItem('init', 'zone')

    blast_run_time = (run.end_time - run.start_time) / 1000
    summary['runtime'] = {}
    summary['runtime']['wallClock'] = blast_run_time
    for phase in run.phase_names:
        total_var = phase + '_time'
        num_var = phase + '_num'
        min_var = phase + '_min'
        max_var = phase + '_max'
        if hasattr(run, total_var):
            summary['runtime'][phase] = {}
            if hasattr(run, num_var):
                summary['runtime'][phase]['num'] = getattr(run, num_var)
            if hasattr(run, total_var):
                summary['runtime'][phase]['totalTime']  = getattr(run, total_var) / 1000
            if hasattr(run, min_var):
                summary['runtime'][phase]['minTime'] = getattr(run, min_var) / 1000
            if hasattr(run, max_var):
                summary['runtime'][phase]['maxTime'] = getattr(run, max_var) / 1000

    summary['blastData'] = {}
    if hasattr(run, 'query_length'):
        summary['blastData']['queryLength'] = run.query_length
    if hasattr(run, 'db_num_seq'):
        summary['blastData']['databaseNumSeq'] = run.db_num_seq
    if hasattr(run, 'db_length'):
        summary['blastData']['databaseLength'] = run.db_length

    if hasattr(run, 'query_length') and hasattr(run, 'max_vcpus'):
        vcpus = run.max_vcpus
        if blast_run_time > 0 and vcpus > 0:
            summary['lettersPerSecondPerCpu'] = int(round(run.query_length / blast_run_time / vcpus))
    summary['numJobs'] = run.njobs
    summary['numJobsFailed'] = nfailed
    summary['exitCode'] = 0 if nfailed == 0 else 1 

    print(json.dumps(summary, indent=2), file=args.output)
    return 0


# Code borrowed from logging module to provide compatibility with their time format
default_time_format = '%Y-%m-%d %H:%M:%S'
default_msec_format = '%s,%03d'


def _format_time(ts):
    fpart, ipart = math.modf(ts+0.0005)  # rounding to milliseconds
    s = time.strftime(default_time_format, time.gmtime(ipart))
    return default_msec_format % (s, fpart*1000)
    # return datetime.utcfromtimestamp(ts).isoformat()


def _read_job_logs_gcp(cfg):
    """ return Run object with number of finished job, start, end, and exit codes,
        and any additional information we can learn about this run """
    dry_run = cfg.cluster.dry_run
    njobs = start_time = end_time = 0
    exit_codes = []
    results = cfg.cluster.results
    if not results:
        return Run()
    log_uri = results + '/' + ELB_LOG_DIR + '/BLAST_RUNTIME-*.out'
#    if self.detailed:
#        print("Checking logs", log_uri)

    cmd = ['gsutil', 'cat', log_uri]
    if dry_run:
        logging.info(' '.join(cmd))
        return Run()
    proc = safe_exec(cmd)
    nread = 0
    njobs = 0
    for line in proc.stdout.decode().split('\n'):
        if not line:
            continue
        nread += 1
        parts = line.split()
        # Failing jobs generate invalid log entries which can
        # start not with a timestamp
        try:
            timestamp = float(parts[0]) / 1e9
        except ValueError:
            continue
        # subj = parts[1]  # should be 'run', we can verify this
        verb = parts[2]
        # nbatch = parts[3]
        # TODO: maybe makes sense to check that there are no duplicates,
        # also check gaps between one batch end and another batch start

        if verb == 'start' and (njobs == 0 or timestamp < start_time):
            start_time = timestamp
        elif verb == 'end' and (njobs == 0 or timestamp > end_time):
            end_time = timestamp
        if verb == 'end':
            njobs += 1
        if verb == 'exitCode':
            exit_codes.append(int(parts[4]))
#    if self.detailed:
#        print(f"Read {nread} lines of logs")
    if not nread:
        logging.error(proc.stderr.read().strip(), file=sys.stderr)
    return Run(njobs, start_time, end_time, exit_codes)


# TODO: use format in blastdbcmd -info so that the database statistics
# become more reliable
re_db_stat = re.compile(r'([,0-9]+) sequences; ([,0-9]+) total')
# These strings should match corresponding signals in download_db_and_search
# script in ncbi/elb docker image
re_blastdbcmdstart = re.compile(r'^Start database download')
re_blastdbcmdend = re.compile(r'^End database download')
re_blastcmdstart = re.compile(r'^Start blast search')
re_blastcmdend = re.compile(r'^End blast search')
re_query_download_start = re.compile(r'^Start quer(y|ies) download')
re_query_download_end = re.compile(r'^End quer(y|ies) download')
re_query_split_start = re.compile(r'^Start query splitting')
re_query_split_end = re.compile(r'^End query splitting')
run_phases = [
    (re_blastdbcmdstart, re_blastdbcmdend, PHASE_BLASTDB_SETUP),
    (re_blastcmdstart, re_blastcmdend, PHASE_BLAST),
    (re_query_download_start, re_query_download_end, PHASE_QUERY_DOWNLOAD),
    (re_query_split_start, re_query_split_end, PHASE_QUERY_SPLIT)
]
class AwsLogParser:
    def __init__(self):
        self.db_num_seq = 0
        self.db_length = 0
        self.start_time = 0
        self.end_time = 0
        self.blastdb_total_time = 0
        self.blast_total_time = 0
        self.blastdb_min_time = 0
        self.blast_min_time = 0
        self.blastdb_max_time = 0
        self.blast_max_time = 0
        self.njobs = 0
        self.exit_codes = []
        self.phase_start_time = 0

    def init_job(self, exit_code):
        self.exit_codes.append(exit_code)
        self.njobs += 1

    def parse_line(self, line):
        """ Parse a line of saved log file """
        parts = line.strip().split('\t')
        if len(parts) <= 1:
            return
        if parts[0] == 'job':
            exit_code = int(parts[2])
            self.init_job(exit_code)
        elif parts[0] == 'cluster_name':
            self.cluster_name = parts[1]
        elif parts[0] == 'instance_type':
            self.instance_type = parts[1]
        elif parts[0] in ('instance_vcpus', 'instance_ram', 'min_vcpus',
                          'max_vcpus', 'num_nodes', 'query_length'):
            setattr(self, parts[0], int(parts[1]))
        else:
            try:
                ts = int(parts[0])
                self.parse(ts, parts[1])
            except ValueError:
                pass

    def parse(self, ts, message):
        """ Parse timestamp and message of a log record """
        if self.start_time == 0 or ts < self.start_time:
            self.start_time = ts
        if ts > self.end_time:
            self.end_time = ts
        # find blastcmd  -info to get database stats
        mo = re_db_stat.search(message)
        if mo:
            self.db_num_seq, self.db_length = map(lambda x: int(re.sub(',', '', x)), mo.groups())
        for re_start, re_end, phase in run_phases:
            mo = re_start.search(message)
            if mo:
                self.phase_start_time = ts
            else:
                mo = re_end.search(message)
                if mo:
                    t = ts - self.phase_start_time
                    total_var = phase + '_time'
                    num_var = phase + '_num'
                    min_var = phase + '_min'
                    max_var = phase + '_max'
                    if hasattr(self, total_var):
                        total = getattr(self, total_var) + t
                    else:
                        total = t
                    setattr(self, total_var, total)
                    if hasattr(self, num_var):
                        n = getattr(self, num_var) + 1
                    else:
                        n = 1
                    setattr(self, num_var, n)
                    if hasattr(self, min_var):
                        val = min(getattr(self, min_var), t)
                    else:
                        val = t
                    setattr(self, min_var, val)
                    if hasattr(self, max_var):
                        val = max(getattr(self, max_var), t)
                    else:
                        val = t
                    setattr(self, max_var, val)

class AwsCompEnv:
    def __init__(self, batch, ec2):
        self.batch = batch
        self.ec2 = ec2
        self.instance_type: str = ''
        self.instance_vcpus: int = 0
        self.instance_ram: int = 0
        self.min_vcpus: int = 0
        self.max_vcpus: int = 0
        self.num_nodes: int = 0
        self.ce_name: str = ''

    def parseJobQueue(self, queue):
        res = self.batch.describe_job_queues(jobQueues=[queue])
        job_queues_descr = res['jobQueues']
        if len(job_queues_descr) < 1:
            # No data for job queue {job_queue}, compute environment probably deleted
            return
        job_queue_descr = job_queues_descr[0]
        ce = job_queue_descr['computeEnvironmentOrder'][0]['computeEnvironment']
        res = self.batch.describe_compute_environments(computeEnvironments=[ce])
        ce_descr = res['computeEnvironments'][0]
        self.ce_name = ce_descr['computeEnvironmentName']
        comp_res = ce_descr['computeResources']
        self.instance_type = comp_res['instanceTypes'][0]
        if self.instance_type != 'optimal':
            res = self.ec2.describe_instance_types(InstanceTypes=[self.instance_type])
            instance_type_descr = res['InstanceTypes'][0]
            self.instance_vcpus = instance_type_descr['VCpuInfo']['DefaultVCpus']
            self.instance_ram = instance_type_descr['MemoryInfo']['SizeInMiB']
            self.min_vcpus = comp_res['minvCpus']
            self.max_vcpus = comp_res['maxvCpus']
            self.num_nodes = int(comp_res['maxvCpus'] / self.instance_vcpus)


def _read_job_logs_aws_from_file(read_logs):
    """ return Run object with number of finished job, start, end, and exit codes,
        and any additional information we can learn about this run """
    log_parser = AwsLogParser()
    for line in read_logs:
        log_parser.parse_line(line)
    
    run = Run(log_parser.njobs, log_parser.start_time, log_parser.end_time, log_parser.exit_codes)
    run.read_log_parser(log_parser)
    return run


@handle_aws_error
def _read_job_logs_aws(cfg, write_logs):
    """ return Run object with number of finished job, start, end, and exit codes,
        and any additional information we can learn about this run """
    dry_run = cfg.cluster.dry_run
    if dry_run:
        return Run()
    boto_cfg = create_aws_config(cfg.aws.region)
    results = cfg.cluster.results
    if not results:
        return Run()

    log_parser = AwsLogParser()

    batch = boto3.client('batch', config=boto_cfg)
    logs = boto3.client('logs', config=boto_cfg)
    s3 = boto3.client('s3', config=boto_cfg)
    ec2 = boto3.client('ec2', config=boto_cfg)

    fname = os.path.join(results, ELB_METADATA_DIR, ELB_AWS_JOB_IDS)
    bucket, key = parse_bucket_name_key(fname)
    resp = s3.get_object(Bucket=bucket, Key=key)
    body = resp['Body']
    job_list = json.loads(body.read().decode())

    if write_logs:
        write_logs.write('AWS job log dump\n')

    # This one is new, so we apply defensive programming here
    query_length = 0
    try:
        fname = os.path.join(results, ELB_METADATA_DIR, ELB_AWS_QUERY_LENGTH)
        bucket, key = parse_bucket_name_key(fname)
        resp = s3.get_object(Bucket=bucket, Key=key)
        body = resp['Body']
        query_length = int(body.read().decode())
        if write_logs:
            write_logs.write(f'query_length\t{query_length}\n')
    except:
        pass

    aws_comp_env = None

    # Need pagination here, maximum jobs returned is 100
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/batch.html#Batch.Client.describe_jobs
    page_size = 100
    for start_job in range(0, len(job_list), page_size):
        res = batch.describe_jobs(jobs=job_list[start_job:start_job+page_size])
        job_descr = res['jobs']

        for job in job_descr:
            job_id = job['jobId']
            job_queue = job['jobQueue']
            if not aws_comp_env:
                aws_comp_env = AwsCompEnv(batch, ec2)
                aws_comp_env.parseJobQueue(job_queue)
                if write_logs:
                    write_logs.write(f'cluster_name\t{aws_comp_env.ce_name}\n')
                    write_logs.write(f'instance_type\t{aws_comp_env.instance_type}\n')
                    write_logs.write(f'instance_vcpus\t{aws_comp_env.instance_vcpus}\n')
                    write_logs.write(f'instance_ram\t{aws_comp_env.instance_ram}\n')
                    write_logs.write(f'min_vcpus\t{aws_comp_env.min_vcpus}\n')
                    write_logs.write(f'max_vcpus\t{aws_comp_env.max_vcpus}\n')
                    write_logs.write(f'num_nodes\t{aws_comp_env.num_nodes}\n')
            status = job['status']
            job_exit_code = JOB_EXIT_CODE_UNINITIALIZED
            reason = ''
            if status == 'SUCCEEDED' or status == 'FAILED':
                attempts = job['attempts']
                if len(attempts) > 0:
                    attempt = attempts[-1]
                    container = attempt['container']
                    if 'exitCode' in container:
                        job_exit_code = container['exitCode']
                        created = job['createdAt'] / 1000
                        started = job['startedAt'] / 1000
                        stopped = job['stoppedAt'] / 1000
                        parameters = job['parameters']
                    else:
                        job_exit_code = JOB_EXIT_CODE_FAILED_WITH_NO_EXIT_CODE
                    if 'reason' in container:
                        reason = '\t'+ container['reason']
                else:
                    # Signal that job failed without attempts
                    job_exit_code = JOB_EXIT_CODE_FAILED_WITH_NO_ATTEMPT
            if write_logs:
                write_logs.write(f'job\t{job_id}\t{job_exit_code}\t{status}{reason}\n')
            log_parser.init_job(job_exit_code)
            container = job['container']
            vcpus = container['vcpus']
            memory = container['memory'] # in MB
            if 'logStreamName' in container:
                log_stream = container['logStreamName']
                logging.debug(f'job {job_id}, queue {job_queue}, status {status}, log stream {log_stream}')
                try:
                    # aws logs get-log-events --log-group-name /aws/batch/job --log-stream-name $log_stream
                    # TODO: need pagination here, logs are about 1MB per return,
                    # need to process nextToken/nextForwardToken
                    # see 
                    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/logs.html#CloudWatchLogs.Client.get_log_events
                    log_events = logs.get_log_events(logGroupName='/aws/batch/job',
                                                    logStreamName=log_stream)
                    events = log_events['events']
                    next_token = log_events['nextForwardToken'] # see comment above
                    for event in events:
                        ts = event['timestamp']
                        message = event['message']
                        if write_logs:
                            escaped_message = message.encode("unicode_escape").decode("utf-8")
#                            decoded_message = escaped_message.encode('utf-8').decode("unicode_escape")
                            write_logs.write(f'{ts}\t{escaped_message}\n')
                        log_parser.parse(ts, message)
                except ClientError as e:
                    # If it's ResourceNotFoundException the log stream is still being copied.
                    # It will be made available eventually, nothing we can sensibly do right now
                    if e.response.get('Error', {}).get('Code', 'Unknown') != 'ResourceNotFoundException':
                        raise

    if query_length:
        log_parser.query_length = query_length
    if aws_comp_env:
        log_parser.cluster_name = aws_comp_env.ce_name
        log_parser.instance_type = aws_comp_env.instance_type
        log_parser.instance_vcpus = aws_comp_env.instance_vcpus
        log_parser.instance_ram = aws_comp_env.instance_ram
        log_parser.min_vcpus = aws_comp_env.min_vcpus
        log_parser.max_vcpus = aws_comp_env.max_vcpus
        log_parser.num_nodes = aws_comp_env.num_nodes

    run = Run(log_parser.njobs, log_parser.start_time, log_parser.end_time, log_parser.exit_codes)
    run.read_log_parser(log_parser)
    return run

