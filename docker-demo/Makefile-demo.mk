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

# Makefile for ElasticBLAST demo
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Tue 06 Oct 2020 11:42:59 AM EDT

SHELL=/bin/bash
.PHONY: all clean distclean check

ELB?=/usr/bin/elastic-blast

GCP_CFG?=elb-gcp-blastn-mane-pdbnt.ini
AWS_CFG?=elb-aws-blastn-mane-pdbnt.ini
GCP_LOG?=elb-gcp.log
AWS_LOG?=elb-aws.log

creds: gcp-creds aws-creds
config: gcp-config aws-config
log: gcp-log aws-log
run: gcp-run aws-run
delete: gcp-delete aws-delete
status: gcp-status aws-status

bucket-suffix.txt:
	openssl rand -hex 3 > $@

version:
	${ELB} --version

gcp-init: bucket-suffix.txt
	sed -i~ -e 's/BUCKET_SUFFIX/$(shell cat $<)/' elb-*.ini
	gsutil mb gs://elasticblast-demo-$(shell cat $<)

gcp-run:
	${ELB} submit --cfg ${GCP_CFG} --logfile ${GCP_LOG} --loglevel DEBUG

gcp-results:
	gsutil ls -lr $(shell awk -F= '/^results/ {print $$2}' ${GCP_CFG})
	gsutil cat $(shell awk -F= '/^results/ {print $$2}' ${GCP_CFG})/batch_000-blastn-pdbnt.out.gz | gzip -cd -

gcp-status:
	${ELB} status --cfg ${GCP_CFG} --logfile ${GCP_LOG} --loglevel DEBUG

gcp-delete:
	${ELB} delete --cfg ${GCP_CFG} --logfile ${GCP_LOG} --loglevel DEBUG

gcp-creds:
	gcloud info

gcp-config:
	cat -n ${GCP_CFG}

gcp-log:
	cat -n ${GCP_LOG}

gcp-distclean:
	gsutil -m rm -r gs://elasticblast-demo-$(shell cat bucket-suffix.txt)


## AWS
aws-init: bucket-suffix.txt
	sed -i~ -e 's/BUCKET_SUFFIX/$(shell cat $<)/' elb-*.ini
	aws s3 mb s3://elasticblast-demo-$(shell cat $<)

aws-run:
	${ELB} submit --cfg ${AWS_CFG} --logfile ${AWS_LOG} --loglevel DEBUG

aws-results:
	aws s3 ls --recursive $(shell awk -F= '/^results/ {print $$2}' ${AWS_CFG})
	aws s3 cp $(shell awk -F= '/^results/ {print $$2}' ${AWS_CFG})/batch_000-blastn-pdbnt.out.gz - | gzip -cd -

aws-status:
	${ELB} status --cfg ${AWS_CFG} --logfile ${AWS_LOG} --loglevel DEBUG

aws-delete:
	${ELB} delete --cfg ${AWS_CFG} --logfile ${AWS_LOG} --loglevel DEBUG

aws-creds:
	aws sts get-caller-identity

aws-config:
	cat -n ${AWS_CFG}

aws-log:
	cat -n ${AWS_LOG}

aws-distclean:
	aws s3 rm s3://elasticblast-demo-$(shell cat bucket-suffix.txt)

distclean:
	${RM} ${GCP_LOG} ${AWS_LOG}

# Demo installation from PyPI
.PHONY: pypi
pypi:
	python3 -m venv .env
	source .env/bin/activate && pip install elastic-blast awscli
	.env/bin/elastic-blast --version
