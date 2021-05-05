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

# Makefile

SHELL=/bin/bash
.PHONY: init delete clean
.PHONY: test smoke_test clear_results get_results test_asn_results
.PHONY: distclean logs monitor show_config
.PHONY: list_resources top ps download_split_queries
.PHONY: credentials check_setup_job

SCRIPTS = elastic-blast.py elb-cost.py blast-tuner.py
VENV?=.env

BLAST_USAGE_REPORT=false

# Cluster/GCP configuration
ELB_CLUSTER_NAME?=elasticblast-${USER}
ELB_NUM_NODES?=1
# FIXME: should this be made the default? Allow enabling via env. var.? Something else? EB-297
ELB_USE_PREEMPTIBLE?=

ELB_AWS_REGION?=us-east-1

# See delete target
ELB_CONFIG_FILE?=

# BLAST configuration
ELB_BLAST_PROGRAM?=blastn
ELB_DB?=pdbnt
ELB_BATCH_LEN?=5000000

# Input/output configuration
ELB_QUERIES ?= gs://elastic-blast-samples/queries/MANE/MANE.GRCh38.v0.8.select_refseq_rna.fna
ELB_RESULTS ?= gs://elasticblast-${USER}

QUERY_BATCHES = ${ELB_RESULTS}/query_batches
MANIFEST_PATH = ${ELB_RESULTS}/MANIFEST

PYTHON_SRC=$(shell find src/elb bin -type f -name "*.py" ! -path "*eggs*" ! -path "*${VENV}*" ! -name __init__.py ! -path "*.tox*" ! -path "*coverage*" ! -path "*cache*" ! -path "./build*")
YAML_TEMPLATES=$(shell find src/elb/templates -type f)

ELB_LOGFILE ?= `pwd`/elastic-blast.log


all: elastic-blast

#############################################################################
# build targets

APPS = $(basename $(SCRIPTS))
.PHONY: apps
apps: ${APPS} 

PYTHON_VERSION=3
elb-cost: ${PYTHON_SRC} ${VENV}
	source ${VENV}/bin/activate && pex --disable-cache . -r requirements/base.txt --python=python${PYTHON_VERSION} -c $@.py -o $@
	-./$@ --version

blast-tuner: ${PYTHON_SRC} ${VENV}
	source ${VENV}/bin/activate && pex --disable-cache . -r requirements/base.txt --python=python${PYTHON_VERSION} -c $@.py -o $@
	-./$@ --version

elastic-blast: ${PYTHON_SRC} ${YAML_TEMPLATES} ${VENV} validate-cf-templates
	source ${VENV}/bin/activate && pex --python-shebang='/usr/bin/env python3' --disable-cache . -r requirements/base.txt --python=python${PYTHON_VERSION} -c $@.py -o $@
	-./$@ --version

elastic-blast3.9: ${PYTHON_SRC} ${YAML_TEMPLATES} ${VENV} validate-cf-templates
	source ${VENV}/bin/activate && pex --disable-cache . -r requirements/base.txt --python=python3.9 -c elastic-blast.py -o $@
	-./$@ --version

elastic-blast3.8: ${PYTHON_SRC} ${YAML_TEMPLATES} ${VENV} validate-cf-templates
	source ${VENV}/bin/activate && pex --disable-cache . -r requirements/base.txt --python=python3.8 -c elastic-blast.py -o $@
	-./$@ --version

elastic-blast3.7: ${PYTHON_SRC} ${YAML_TEMPLATES} ${VENV} validate-cf-templates
	source ${VENV}/bin/activate && pex --disable-cache . -r requirements/base.txt --python=python3.7 -c elastic-blast.py -o $@
	-./$@ --version

%.md5: %
	md5sum $< >$@

#############################################################################
# gcloud/k8s targets

init:
	@if [ "${ELB_GCP_PROJECT}" == "" ] ; then echo "ELB_GCP_PROJECT environment variable must be defined"; exit 1; fi
	@if [ "${ELB_GCP_ZONE}" == "" ] ; then echo "ELB_GCP_ZONE environment variable must be defined"; exit 1; fi
	@if [ "${ELB_GCP_REGION}" == "" ] ; then echo "ELB_GCP_REGION environment variable must be defined"; exit 1; fi
	gcloud config set project ${ELB_GCP_PROJECT}
	gcloud config set compute/zone ${ELB_GCP_ZONE}
	gcloud config set compute/region ${ELB_GCP_REGION}
	command -v kubectl >&/dev/null
	command -v python3 >&/dev/null

credentials: init
	gcloud container clusters get-credentials ${ELB_CLUSTER_NAME}

delete: elastic-blast
	[ ! -z "${ELB_CONFIG_FILE}" ] || { echo "ELB_CONFIG_FILE environment variable must be defined"; exit 1; }
	-./elastic-blast delete --loglevel DEBUG --logfile stderr --cfg ${ELB_CONFIG_FILE}

clear_jobs: credentials
	-kubectl delete job -l app=test
	-kubectl delete job -l app=blast
	-kubectl delete job -l app=setup

# install kubectl
kubectl:
	curl -LO https://storage.googleapis.com/kubernetes-release/release/`curl -s https://storage.googleapis.com/kubernetes-release/release/stable.txt`/bin/linux/amd64/kubectl
	chmod +x ./kubectl

#############################################################################
# Python support

${VENV}: requirements/base.txt requirements/test.txt
	[ -d ${VENV} ] || python3 -m venv $@
	source ${VENV}/bin/activate && pip3 install -qe . -r requirements/test.txt
	source ${VENV}/bin/activate && python3 setup.py install_data

#############################################################################
# Testing targets
smoke_test: ${VENV} check_version_help pylint mypy cfn-lint
	source ${VENV}/bin/activate && python3 -m py_compile ${PYTHON_SRC}
	source ${VENV}/bin/activate && pytest -vx
	source ${VENV}/bin/activate && fasta_split.py <(blastdbcmd -entry NC_000001 -db 9606_genomic) -o /tmp -t src/elb/templates/blast-batch-job.yaml.template && [ -f /tmp/batch_000.fa ];
	${RM} /tmp/batch_000.fa
	# Test batch length that exactly matches length of the first batch
	source ${VENV}/bin/activate && TEST_BATCH_LENGTH=1960 pytest $(shell find . -name test_fasta_split.py) -k TestSplitResultMatchesOriginal
	# EB-108 test case
	source ${VENV}/bin/activate && TEST_URL=gs://elastic-blast-samples/queries/protein/dark-matter-1M.faa.gz TEST_BATCH_LENGTH=20000 pytest $(shell find . -name test_fasta_split.py) -k TestSplitResultMatchesOriginal


AWS_ACCOUNT=$(shell aws sts get-caller-identity --output json | jq -r .Account)
iam-policy.json: share/etc/elastic-blast-aws-iam-policy.json.template
	AWS_ACCOUNT=${AWS_ACCOUNT} envsubst < $< > $@

.PHONY: validate-iam-policy
validate-iam-policy: iam-policy.json
	#-AWS_PAGER='' aws accessanalyzer validate-policy --no-paginate --policy-document file://$< --policy-type IDENTITY_POLICY
	-AWS_PAGER='' aws accessanalyzer validate-policy --no-paginate --policy-document file://$< --policy-type RESOURCE_POLICY

.PHONY: validate-cf-templates
validate-cf-templates: src/elb/templates/elastic-blast-cf.yaml
	AWS_PAGER='' aws --region us-east-1 cloudformation validate-template --template-body file://$<

.PHONY: cfn-lint
cfn-lint: src/elb/templates/elastic-blast-cf.yaml ${VENV}
	source ${VENV}/bin/activate && cfn-lint -t $<

.PHONY: check_version_help
check_version_help: ${VENV}
	for app in ${SCRIPTS}; do source ${VENV}/bin/activate && $$app --version; done
	for app in ${SCRIPTS}; do source ${VENV}/bin/activate && $$app -h; done

ELB_TEST_TIMEOUT_HEPATITIS_VS_NT?=95
ELB_TEST_TIMEOUT_MANE_VS_PDBNT?=15
ELB_TEST_TIMEOUT_MANE_VS_PDBNT_OPTIMAL_INSTANCE_TYPE?=30
ELB_TEST_TIMEOUT_COALA_VS_NR?=120
ELB_TEST_TIMEOUT_BLASTP_VIRAL_METAGENOME_VS_NR?=130
ELB_TEST_TIMEOUT_BLASTX_WB4_2_0811_VS_NR=180
ELB_TEST_TIMEOUT_TBLASTN_VIRAL_META_VS_NT=90
ELB_TEST_TIMEOUT_TBLASTX_BDQE01=30
ELB_TEST_TIMEOUT_RPSBLAST_AMR=40
ELB_TEST_TIMEOUT_RPSTBLASTN_WB4_2_0811=30
ELB_TEST_TIMEOUT_VIRAL_METAGENOMES_VS_SWISSPROT?=40
ELB_TEST_TIMEOUT_ALGAE_BACTERIUM_VS_NR?=6000
ELB_TEST_TIMEOUT_CORONAVIRUS_VS_ITSELF?=20
ELB_TEST_TIMEOUT_DB_DOWNLOAD?=60
#ELB_TEST_TIMEOUT_CORONAVIRUS_VS_NT?=120
ELB_TEST_TIMEOUT_RPSTBLASTN_FIVE?=86400

ELB_TEST_TIMEOUT_BLASTN_NOPAL?=90
ELB_TEST_TIMEOUT_BLASTX_NOPAL?=388800 # Based on EB-719: 20% more than 90 hours
ELB_TEST_TIMEOUT_BLASTP_NOPAL?=960 # Based on EB-718: 20% more than 13h:20m (i.e.: 960 mins)

ELB_TEST_TIMEOUT_BLASTN_16S_CHICKEN_GUT_METAGENOME?=10300 # Based on EB-736: 20% more than 143h (i.e.: 8,580 mins)

#############################################################################
# Real world, performance tests

.PHONY: aws_regression_blastn_16s_chicken_gut_metagenome
aws_regression_blastn_16s_chicken_gut_metagenome: elastic-blast
	-ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-aws-blastn-chicken-gut-metagenome.ini ${ELB_TEST_TIMEOUT_BLASTN_16S_CHICKEN_GUT_METAGENOME}

.PHONY: gcp_regression_blastn_16s_chicken_gut_metagenome
gcp_regression_blastn_16s_chicken_gut_metagenome: elastic-blast
	-ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastn-chicken-gut-metagenome-autoscale.ini ${ELB_TEST_TIMEOUT_BLASTN_16S_CHICKEN_GUT_METAGENOME}

.PHONY: aws_regression_blastn_nopal
aws_regression_blastn_nopal: elastic-blast
	-ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-aws-blastn-nopal-transcriptome.ini ${ELB_TEST_TIMEOUT_BLASTN_NOPAL}

.PHONY: aws_regression_blastx_nopal
aws_regression_blastx_nopal: elastic-blast
	-ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-aws-blastx-nopal-transcriptome.ini ${ELB_TEST_TIMEOUT_BLASTX_NOPAL}

.PHONY: aws_regression_blastp_nopal
aws_regression_blastp_nopal: elastic-blast
	-ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-aws-blastp-nopal-transcriptome.ini ${ELB_TEST_TIMEOUT_BLASTP_NOPAL}

.PHONY: gcp_regression_blastn_nopal
gcp_regression_blastn_nopal: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastn-nopal-transcriptome.ini ${ELB_TEST_TIMEOUT_BLASTN_NOPAL}

.PHONY: gcp_regression_blastx_nopal
gcp_regression_blastx_nopal: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastx-nopal-transcriptome.ini ${ELB_TEST_TIMEOUT_BLASTX_NOPAL}

.PHONY: gcp_regression_blastp_nopal
gcp_regression_blastp_nopal: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastp-nopal-transcriptome.ini ${ELB_TEST_TIMEOUT_BLASTP_NOPAL}

.PHONY: aws_regression_rpstblastn_vs_split_cdd_five_autoscale_async
aws_regression_rpstblastn_vs_split_cdd_five_autoscale_async: elastic-blast
	-ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-aws-rpstblastn-five-example.ini ${ELB_TEST_TIMEOUT_RPSTBLASTN_FIVE}

.PHONY: regression_rpstblastn_vs_split_cdd_five_autoscale_async
regression_rpstblastn_vs_split_cdd_five_autoscale_async: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-rpstblastn-five-example.ini ${ELB_TEST_TIMEOUT_RPSTBLASTN_FIVE}

#############################################################################

.PHONY: regression_nr_vs_algae_bacterium_multi_node_sync_autoscale
regression_nr_vs_algae_bacterium_multi_node_sync_autoscale: elastic-blast
	#ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-psiblast-nr-autoscale.ini ${ELB_TEST_TIMEOUT_ALGAE_BACTERIUM_VS_NR}
	true

.PHONY: regression_nr_vs_algae_bacterium_multi_node_sync
regression_nr_vs_algae_bacterium_multi_node_sync: elastic-blast
	#ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-psiblast-nr.ini ${ELB_TEST_TIMEOUT_ALGAE_BACTERIUM_VS_NR}
	true

.PHONY: regression_psiblast_swissprot_vs_viral_metagenomes_sync
regression_psiblast_swissprot_vs_viral_metagenomes_sync: elastic-blast
	#ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-psiblast-swissprot.ini ${ELB_TEST_TIMEOUT_VIRAL_METAGENOMES_VS_SWISSPROT}
	true

.PHONY: regression_psiblast_swissprot_vs_viral_metagenomes
regression_psiblast_swissprot_vs_viral_metagenomes: elastic-blast
	ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-psiblast-swissprot.ini ${ELB_TEST_TIMEOUT_VIRAL_METAGENOMES_VS_SWISSPROT}

.PHONY: regression_coronavirus_sync
regression_coronavirus_sync: elastic-blast
	#ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-blastn-nt-coronaviridae.ini ${ELB_TEST_TIMEOUT_CORONAVIRUS_VS_ITSELF}
	true

# FIXME this doesn't work, depends on EB-300
.PHONY: regression_coronavirus_sync_autoscale
regression_coronavirus_sync_autoscale: elastic-blast
	#ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-blastn-nt-coronaviridae-autoscale.ini ${ELB_TEST_TIMEOUT_CORONAVIRUS_VS_ITSELF}
	true

.PHONY: aws_regression_pdbnt_vs_mane_single_node_sync_create_resources
aws_regression_pdbnt_vs_mane_single_node_sync_create_resources: elastic-blast
	#-ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-aws-blastn-pdbnt-s3-query-create-resources.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}
	true

# Test creation of VPC with as many subnets as there are AZs in a region and spot instances
.PHONY: aws_regression_pdbnt_vs_mane_multi_node_create_resources_all_azs_spot
aws_regression_pdbnt_vs_mane_multi_node_create_resources_all_azs_spot: elastic-blast
	-ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-aws-blastn-pdbnt-s3-query-create-resources-small-instance.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}

.PHONY: aws_regression_pdbnt_vs_mane_single_node_create_resources
aws_regression_pdbnt_vs_mane_single_node_create_resources: elastic-blast
	-ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-aws-blastn-pdbnt-s3-query-create-resources.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}

.PHONY: aws_regression_blastn_non_default_params
aws_regression_blastn_non_default_params: elastic-blast
	-ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-aws-blastn-non-default-params.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}
	test $$(zcat batch_000.out.gz | wc -l) -eq 5 

.PHONY: aws_regression_pdbnt_vs_mane_single_node_sync
aws_regression_pdbnt_vs_mane_single_node_sync: elastic-blast
	#-ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-aws-blastn-pdbnt.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}
	true

# THIS IS EXPERIMENTAL, doesn't always work
.PHONY: aws_regression_pdbnt_vs_mane_optimal_instance_type
aws_regression_pdbnt_vs_mane_optimal_instance_type: elastic-blast
	-ELB_RESULTS_BUCKET=${ELB_RESULTS_BUCKET} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-aws-spot-optimal-instance-type-blastn-pdbnt.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT_OPTIMAL_INSTANCE_TYPE}

.PHONY: aws_regression_nt_vs_hepatitis_multi_node_sync
aws_regression_nt_vs_hepatitis_multi_node_sync: elastic-blast
	#-ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-aws-blastn-nt-8-nodes.ini ${ELB_TEST_TIMEOUT_HEPATITIS_VS_NT}
	true

.PHONY: aws_regression_blastp_pataa_vs_dark_matter_multi_node_sync
aws_regression_blastp_pataa_vs_dark_matter_multi_node_sync: elastic-blast
	#-ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-aws-blastp-nr-s3-query-create-resources.ini ${ELB_TEST_TIMEOUT_HEPATITIS_VS_NT}
	true

.PHONY: aws_regression_blastn_taxid_filtering
aws_regression_blastn_taxid_filtering: elastic-blast
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-aws-blastn-taxidfiltering.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}
	test $$(zcat batch_000.out.gz | grep 246196 | wc -l) -gt 0
	test $$(zcat batch_000.out.gz | grep 3562 | wc -l) -gt 0
	test $$(zcat batch_000.out.gz | cut -f 13 | sort | uniq | wc -l) -eq 2 

.PHONY: aws_regression_blastn_multi_file
aws_regression_blastn_multi_file: elastic-blast
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-aws-blastn-multiple-query-files.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}
	test $$(cat batch_003.fa | awk '/>/ {print substr($$L, 1, 11);}' | grep SRR5665118 | wc -l) -gt 0
	test $$(cat batch_003.fa | awk '/>/ {print substr($$L, 1, 11);}' | grep SRR5665119 | wc -l) -gt 0
	test $$(cat batch_004.fa | awk '/>/ {print substr($$L, 1, 11);}' | grep RFQT0100 | wc -l) -gt 0

.PHONY: regression_blastn_multi_file
regression_blastn_multi_file: elastic-blast
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastn-multiple-query-files.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}
	test $$(cat batch_003.fa | awk '/>/ {print substr($$L, 1, 11);}' | grep SRR5665118 | wc -l) -gt 0
	test $$(cat batch_003.fa | awk '/>/ {print substr($$L, 1, 11);}' | grep SRR5665119 | wc -l) -gt 0
	test $$(cat batch_004.fa | awk '/>/ {print substr($$L, 1, 11);}' | grep RFQT0100 | wc -l) -gt 0

.PHONY: regression_blastn_taxid_filtering
regression_blastn_taxid_filtering: elastic-blast
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastn-taxidfiltering.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}
	test $$(zcat batch_000-blastn-pdbnt.out.gz | grep 246196 | wc -l) -gt 0
	test $$(zcat batch_000-blastn-pdbnt.out.gz | grep 3562 | wc -l) -gt 0
	test $$(zcat batch_000-blastn-pdbnt.out.gz | cut -f 13 | sort | uniq | wc -l) -eq 2 

.PHONY: regression_nt_vs_hepatitis_multi_node_sync
regression_nt_vs_hepatitis_multi_node_sync: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-blastn-nt-eb239.ini ${ELB_TEST_TIMEOUT_HEPATITIS_VS_NT}
	true

.PHONY: regression_nt_vs_hepatitis_multi_node
regression_nt_vs_hepatitis_multi_node: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastn-nt-eb239.ini ${ELB_TEST_TIMEOUT_HEPATITIS_VS_NT}

.PHONY: regression_tblastx_BDQE01_vs_ref_virus_multi_node_sync
regression_tblastx_BDQE01_vs_ref_virus_multi_node_sync: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-tblastx-virusrep.ini ${ELB_TEST_TIMEOUT_TBLASTX_BDQE01}
	true

.PHONY: regression_tblastx_BDQE01_vs_ref_virus_multi_node
regression_tblastx_BDQE01_vs_ref_virus_multi_node: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-tblastx-virusrep.ini ${ELB_TEST_TIMEOUT_TBLASTX_BDQE01}

.PHONY: regression_nt_vs_hepatitis_multi_node_sync_autoscale
regression_nt_vs_hepatitis_multi_node_sync_autoscale: elastic-blast
	#ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-blastn-nt-eb239-autoscale.ini ${ELB_TEST_TIMEOUT_HEPATITIS_VS_NT}
	true

.PHONY: regression_nt_vs_hepatitis_multi_node_autoscale
regression_nt_vs_hepatitis_multi_node_autoscale: elastic-blast
	ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastn-nt-eb239-autoscale.ini ${ELB_TEST_TIMEOUT_HEPATITIS_VS_NT}

.PHONY: regression_nr_vs_coala_multi_node_sync
regression_nr_vs_coala_multi_node_sync: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-slava-blastp-nr.ini ${ELB_TEST_TIMEOUT_COALA_VS_NR}
	true

.PHONY: regression_nr_vs_coala_multi_node
regression_nr_vs_coala_multi_node: elastic-blast
	#ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-slava-blastp-nr.ini ${ELB_TEST_TIMEOUT_COALA_VS_NR}
	true

.PHONY: regression_nr_vs_coala_multi_node_sync_autoscale
regression_nr_vs_coala_multi_node_sync_autoscale: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-slava-blastp-nr-autoscale.ini ${ELB_TEST_TIMEOUT_COALA_VS_NR}
	true

.PHONY: regression_nr_vs_coala_multi_node_autoscale
regression_nr_vs_coala_multi_node_autoscale: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-slava-blastp-nr-autoscale.ini ${ELB_TEST_TIMEOUT_COALA_VS_NR}
	true

.PHONY: regression_blastp_nr_vs_viral_metagenome_sync
regression_nr_vs_viral_metagenome_multi_node_sync: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-blastp-nr-viral-metagenome.ini ${ELB_TEST_TIMEOUT_BLASTP_VIRAL_METAGENOME_VS_NR}
	true

.PHONY: regression_blastp_nr_vs_viral_metagenome
regression_nr_vs_viral_metagenome_multi_node: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastp-nr-viral-metagenome.ini ${ELB_TEST_TIMEOUT_BLASTP_VIRAL_METAGENOME_VS_NR}

.PHONY: regression_blastx_nr_vs_WB4_2_0811_sync
regression_blastx_nr_vs_WB4_2_0811_sync: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-blastx-nr-WB4_2_0811.ini ${ELB_TEST_TIMEOUT_BLASTX_WB4_2_0811_VS_NR}
	true

.PHONY: regression_blastx_nr_vs_WB4_2_0811
regression_blastx_nr_vs_WB4_2_0811: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastx-nr-WB4_2_0811.ini ${ELB_TEST_TIMEOUT_BLASTX_WB4_2_0811_VS_NR}

.PHONY: regression_tblastn_nt_vs_viral_metagenome_sync
regression_tblastn_nt_vs_viral_metagenome_sync: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-tblastn-nt-viral-metagenome.ini ${ELB_TEST_TIMEOUT_TBLASTN_VIRAL_META_VS_NT}
	true

.PHONY: regression_tblastn_nt_vs_viral_metagenome
regression_tblastn_nt_vs_viral_metagenome: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-tblastn-nt-viral-metagenome.ini ${ELB_TEST_TIMEOUT_TBLASTN_VIRAL_META_VS_NT}

.PHONY: regression_rpsblast_vs_amr_sync
regression_rpsblast_vs_amr_sync: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-rpsblast-amr.ini ${ELB_TEST_TIMEOUT_RPSBLAST_AMR}
	true

.PHONY: regression_rpsblast_vs_amr
regression_rpsblast_vs_amr: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-rpsblast-amr.ini ${ELB_TEST_TIMEOUT_RPSBLAST_AMR}

.PHONY: regression_rpstblastn_vs_wb4_2_0811_sync
regression_rpstblastn_vs_wb4_2_0811_sync: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-rpstblastn-WB4_2_0811.ini ${ELB_TEST_TIMEOUT_RPSTBLASTN_WB4_2_0811}
	true

.PHONY: regression_rpstblastn_vs_wb4_2_0811
regression_rpstblastn_vs_wb4_2_0811: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-rpstblastn-WB4_2_0811.ini ${ELB_TEST_TIMEOUT_RPSTBLASTN_WB4_2_0811}

.PHONY: regression_blastn_vs_custom_db_sync
regression_blastn_vs_custom_db_sync: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-blastn-custom-db.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}
	true

.PHONY: regression_blastn_vs_custom_db
regression_blastn_vs_custom_db: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastn-custom-db.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}

.PHONY: integration_test_pdbnt_single_node
integration_test_pdbnt_single_node: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastn-pdbnt.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}

.PHONY: integration_test_pdbnt_single_node_sync
integration_test_pdbnt_single_node_sync: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-blastn-pdbnt.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}
	true

.PHONY: integration_test_pdbnt_multi_node_autoscale
integration_test_pdbnt_multi_node_autoscale: elastic-blast
	-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh share/etc/elb-blastn-pdbnt-autoscale.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}

.PHONY: integration_test_pdbnt_multi_node_autoscale_sync
integration_test_pdbnt_multi_node_autoscale_sync: elastic-blast
	#-ELB_GCP_PROJECT=${ELB_GCP_PROJECT} \
	#ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} \
	#ELB_RESULTS=${ELB_RESULTS} \
	#	tests/tc-bash-runner.sh tests/integration-test-synchronous.sh share/etc/elb-blastn-pdbnt-autoscale.ini ${ELB_TEST_TIMEOUT_MANE_VS_PDBNT}
	true

blastdb-manifest.json:
	gsutil cp gs://blast-db/$$(gsutil cat gs://blast-db/latest-dir)/blastdb-manifest.json .


.PHONY: %-download-test
%-download-test: DB=$(subst -download-test,,$@)
%-download-test: PROGRAM=$(shell if grep -q $(DB).*nsq blastdb-manifest.json ; then echo blastn; else echo blastp; fi)
%-download-test: DB_LABEL=$(subst _,-,$(shell echo $(DB) | tr '[:upper:]' '[:lower:]'))
%-download-test: QMOL=$(shell if [[ $(PROGRAM) == blastp ]] ; then echo prot; else echo nucl; fi)
%-download-test: QUERY=/panfs/pan1.be-md.ncbi.nlm.nih.gov/blastprojects/elastic-blast-test-queries/tiny_$(QMOL).fa
%-download-test: INIFILE=$(DB).ini
%-download-test: OPTIONS=$(shell if [[ $(DB) == ref_euk_rep_genomes ]] ; then echo \"-db_soft_mask 103\"; fi)
%-download-test: MACHINE_TYPE=$(shell if [[ $(DB) == ref_euk_rep_genomes ]] ; then echo "n1-standard-96"; else echo "n1-standard-32"; fi)
%-download-test: elastic-blast blastdb-manifest.json
	DB=$(DB) \
	DB_LABEL=$(DB_LABEL) \
	PROGRAM=$(PROGRAM) \
	QUERY=$(QUERY) \
	OPTIONS=$(OPTIONS) \
	MACHINE_TYPE=$(MACHINE_TYPE) \
	    envsubst <share/etc/elb-blastdb-download-test.template >$(INIFILE)
	ELB_RESULTS=${ELB_RESULTS} \
		tests/tc-bash-runner.sh tests/integration-test.sh $(DB_LABEL) $(INIFILE) ${ELB_TEST_TIMEOUT_DB_DOWNLOAD}

.PHONY: test-blastdb-downloads
test-blastdb-downloads: DB_TARGETS=$(addsuffix -download-test, $(shell update_blastdb.pl --source gcp --showall | grep -v ^Connected ))
test-blastdb-downloads:
	#$(MAKE) $(DB_TARGETS)  # Turned off for now, will be addressed in EB-554
	true


.PHONY: test_script_based_interface_dry_run
test_script_based_interface_dry_run: export ELB_USE_PREEMPTIBLE=1
test_script_based_interface_dry_run: export ELB_GCP_PROJECT=foo
test_script_based_interface_dry_run: export ELB_GCP_REGION=bar
test_script_based_interface_dry_run: export ELB_GCP_ZONE=baz
test_script_based_interface_dry_run: elastic-blast
	./elastic-blast submit \
		--results ${ELB_RESULTS} \
		--program ${ELB_BLAST_PROGRAM} \
		--db ${ELB_DB} \
		--query ${ELB_QUERIES} \
		--num-nodes ${ELB_NUM_NODES} \
		--dry-run --logfile stderr --loglevel DEBUG
	./elastic-blast status --dry-run --results gs://user-bucket --logfile stderr --loglevel DEBUG 
	./elastic-blast delete --cfg share/etc/elb-blastn-pdbnt.ini --results gs://user-bucket --loglevel DEBUG --dry-run --logfile stderr
	./elastic-blast submit --dry-run --cfg share/etc/elb-blastn-pdbnt-autoscale.ini --results gs://user-bucket --loglevel DEBUG --logfile stderr
	./elastic-blast run-summary --cfg share/etc/elb-blastn-pdbnt.ini --results gs://user-bucket --loglevel DEBUG --dry-run --logfile stderr

	#./elastic-blast submit \
	#	--program ${ELB_BLAST_PROGRAM} \
	#	--db ${ELB_DB} \
	#	--query ${ELB_QUERIES} \
	#	--num-nodes ${ELB_NUM_NODES} \
	#	--dry-run --logfile stderr --loglevel DEBUG
	#./elastic-blast status --dry-run --logfile stderr --loglevel DEBUG 
.PHONY: aws_test_script_based_interface_dry_run
aws_test_script_based_interface_dry_run: elastic-blast
	./elastic-blast delete --dry-run --cfg share/etc/elb-aws-blastn-pdbnt.ini --loglevel DEBUG --logfile stderr
	./elastic-blast submit --dry-run --cfg share/etc/elb-aws-blastn-pdbnt.ini --loglevel DEBUG --logfile stderr

.PHONY: blast-tuner-smoke-test
blast-tuner-smoke-test: ${VENV} bin/blast-tuner.py
	source ${VENV}/bin/activate && blast-tuner.py --db nr --program blastx
	source ${VENV}/bin/activate && blast-tuner.py -h
	source ${VENV}/bin/activate && blast-tuner.py --db this-db-does-not-exist
	source ${VENV}/bin/activate && blast-tuner.py --program magicblast; \
		if [ $$? -eq 0 ] ; then \
		echo "blast-tuner.py error: should exit with non-zero for unsupported program"; exit 1; \
		fi

# FIXME: add this to smoke_test target, add other YAML files as well
.PHONY: yamllint
yamllint: ${VENV}
	source ${VENV}/bin/activate && \
		yamllint -d share/etc/yamllint-config.yaml src/elb/templates/elastic-blast-cf.yaml
	source ${VENV}/bin/activate && \
		yamllint -d share/etc/yamllint-config.yaml src/elb/templates/storage-gcp.yaml
	source ${VENV}/bin/activate && \
		yamllint -d share/etc/yamllint-config.yaml src/elb/templates/storage-gcp-ssd.yaml
	source ${VENV}/bin/activate && \
		yamllint -d share/etc/yamllint-config.yaml src/elb/templates/pvc.yaml.template
	source ${VENV}/bin/activate && \
		yamllint -d share/etc/yamllint-config.yaml src/elb/templates/job-init-*
	source ${VENV}/bin/activate && \
		yamllint -d share/etc/yamllint-config.yaml src/elb/templates/blast-batch-job*

.PHONY: pylint
pylint: ${VENV}
	if [ ! -z "${TEAMCITY_PROJECT_NAME}" ]; then ARGS="--output-format=teamcity.pylint_reporter.TeamCityReporter"; fi; \
	source ${VENV}/bin/activate && pylint --rcfile .pylintrc $$ARGS ${PYTHON_SRC}

.PHONY: mypy
mypy: ${VENV}
	source ${VENV}/bin/activate && mypy src/elb/

check_k8s:
	-kubectl delete -f share/test 2>/dev/null
	-kubectl apply -f share/test
	-time kubectl wait --for=condition=complete -f share/test/job-show-blastdbs.yaml

test: check_k8s ${VENV}
	source ${VENV}/bin/activate && python3 setup.py test
	# This tests splitting FASTA into ~20,000 files and uploading it to GCP
	source ${VENV}/bin/activate && tests/fasta_split/performance-test.sh 3m

.PHONY: test_summary
test_summary: ${VENV}
	source ${VENV}/bin/activate && elastic-blast run-summary.py --cfg FIXME
	source ${VENV}/bin/activate && tests/run_summary_correctness_test.py elb-run-summary.json

#############################################################################
# Operational targets
get_results:
	gsutil -qm cp ${ELB_RESULTS}/*.out.gz .
	-gsutil -qm cp ${ELB_RESULTS}/metadata/* .

test_asn_results: get_results download_split_queries
	find . -name "batch*.out.gz" -type f -print0 | xargs -0 -P8 -I{} -t gzip -t {}
	find . -name "batch*.out.gz" -type f -print0 | xargs -0 -P8 -I{} -t bash -c "zcat {} | datatool -m /netopt/ncbi_tools64/c++.metastable/src/objects/blast/blast.asn -M /am/ncbiapdata/asn/asn.all -v - -e /dev/null"
	test $(shell ls -1 *fa | wc -l) -eq $(shell ls *.out.gz | wc -l)
	test $(shell du -a -b *.out.gz | sort -n | head -n 1 | cut -f 1) -gt 0

download_split_queries:
	-gsutil -qm cp ${QUERY_BATCHES}/*.fa .

clear_results:
	-gsutil -qm rm ${ELB_RESULTS}/*.out.gz
	-gsutil -qm rm ${ELB_RESULTS}/*.fa
	-gsutil -qm rm ${ELB_RESULTS}/*.out
	-gsutil -qm rm ${ELB_RESULTS}/*.asn
	-gsutil -qm rm -rf ${ELB_RESULTS}/metadata
	-gsutil -qm rm -rf ${ELB_RESULTS}/logs
	-gsutil -qm rm -rf ${ELB_RESULTS}/query_batches

clean: delete
	${RM} elastic-blast elb-cost blast-tuner iam-policy.json
	${RM} ${ELB_LOGFILE}
	${RM} elb-run-summary.json
	-gsutil -qm rm -rf ${ELB_RESULTS}/metadata
	-gsutil -qm rm -rf ${ELB_RESULTS}/logs
	${RM} -r ${VENV} .tox htmlcov
	find . -name __pycache__ | xargs ${RM} -rf

distclean: clear_results clean 
	(cd share/test && ${RM} *.out.gz *.fa *.fsa ${ELB_DB}.* taxdb.* *.out *.asn)

show_config:
	env | grep ^ELB | sort
	-printenv KUBECONFIG

# Replaces prepare-binaries build step
.PHONY: tc-copy-elastic-blast-dep
tc-copy-elastic-blast-dep:
	pwd
	ls -lR
	cp -v build_deps/* .
	touch .env elastic-blast*
	-ls -ltr ${PYTHON_SOURCE} ${YAML_TEMPLATES} ${VENV} elastic-blast

#############################################################################
# Release management targets

VERSION=$(shell ./elastic-blast --version | sed -e 's/elastic-blast //' )
.PHONY: release
release: ${VENV} elastic-blast
	. ${VENV}/bin/activate && python3 setup.py sdist
	mv dist/elb-${VERSION}.tar.gz elb-${VERSION}.tgz

# FIXME: this tarball includes elb-${VERSION}/share/blast_specs/blast-batch-000.yaml, which it shuld not, do not use. It's only here for reference (for now)
.PHONY: artifactory-release
artifactory-release:
	curl -sO https://artifactory.ncbi.nlm.nih.gov/artifactory/python-local-repo/elb/${VERSION}/elb-${VERSION}.tar.gz
	tar atvf elb-${VERSION}.tar.gz

RELEASE_BUCKET=gs://elastic-blast/release
.PHONY: release_sources_to_public
release_sources_to_public:
	gsutil -q stat ${RELEASE_BUCKET}/elb-${VERSION}.tgz; \
	     if [ $$? -eq 0 ] ; then \
		 	echo "Warning: elb-${VERSION} was already released."; \
		 else \
			gsutil cp elb-${VERSION}.tgz ${RELEASE_BUCKET}/; \
			@echo "elb-${VERSION} released to ${RELEASE_BUCKET}";  \
		 fi

DEPLOY_DIR=/panfs/pan1.be-md.ncbi.nlm.nih.gov/blastprojects/releases/elastic-blast
.PHONY: deploy_pex
deploy_pex: elastic-blast
	[ -d ${DEPLOY_DIR}/${VERSION} ] || mkdir -m 0775 ${DEPLOY_DIR}/${VERSION}
	chmod g+w $<
	cp -p $< ${DEPLOY_DIR}/${VERSION}/
	md5sum $< > ${DEPLOY_DIR}/${VERSION}/elastic-blast.md5
	chmod g+w ${DEPLOY_DIR}/${VERSION}/elastic-blast.md5

.PHONY: release_pex_to_public
release_pex_to_public: deploy_pex
	gsutil -q stat ${RELEASE_BUCKET}/${VERSION}/elastic-blast; \
	     if [ $$? -eq 0 ] ; then \
		 	echo "Warning: elastic-blast ${VERSION} was already released to GCS."; \
		 else \
			gsutil -qm cp elastic-blast ${RELEASE_BUCKET}/; \
			@echo "elastic-blast ${VERSION} released to ${RELEASE_BUCKET}";  \
		 fi

# FIXME: these links don't work yet, need to fix version and probably configure it correctly
#curl -I https://artifactory.ncbi.nlm.nih.gov/artifactory/do-dev/elb/elb-0.0.2-8.tar.gz
#curl -s https://artifactory.ncbi.nlm.nih.gov/artifactory/do-dev/elb/elb-0.0.2-8.tar.gz | tar ztvf -

#############################################################################
# Monitoring targets
monitor:
	kubectl get pods -o wide
	-kubectl top pods --containers
	kubectl top nodes

progress:
	for status in Pending Running Succeeded Failed; do \
		echo -n "$$status "; \
		echo `kubectl get pods -l app=blast --field-selector=status.phase=$$status -o name| wc -l`; \
	done

check_setup_job:
	-kubectl logs -l app=setup
	-kubectl describe jobs -l app=setup

top:
	kubectl get pods -o name -l app=blast | sed 's,pod/,,' | xargs -t -I{} kubectl exec {} -c blast -- top -n1 -cb

ps:
	kubectl get pods -o name -l app=blast | sed 's,pod/,,' | xargs -t -I{} kubectl exec {} -c blast -- ps aux

logs:
	-kubectl logs --timestamps --since=24h --tail=-1 -l app=setup -c get-blastdb
	-kubectl logs --timestamps --since=24h --tail=-1 -l app=setup -c import-query-batches
	-kubectl logs --timestamps --since=24h --tail=-1 -l app=test
	-kubectl logs --timestamps --since=24h --tail=-1 -l app=blast -c load-blastdb-into-ram
	-kubectl logs --timestamps --since=24h --tail=-1 -l app=blast -c blast
	-kubectl logs --timestamps --since=24h --tail=-1 -l app=blast -c results-export

list_resources: init
	-gcloud container clusters list
	-gcloud compute disks list
	-gcloud compute instances list

aws_list_resources: export AWS_PAGER=
aws_list_resources: creds.sh
	-aws cloudformation describe-stacks --stack-name ${ELB_CLUSTER_NAME}
	-aws ec2 describe-instances --filter Name=tag:billingcode,Values=elastic-blast Name=tag:Owner,Values=${USER} --output json | jq -r '.Reservations[].Instances[] | .PublicDnsName + " " + .PublicIpAddress'
	-aws batch describe-job-queues --output json
	-aws batch describe-job-definitions --status ACTIVE --output json
	-aws batch describe-compute-environments --output json

aws_monitor: creds.sh
	-source creds.sh && aws batch describe-jobs --jobs `aws s3 cp ${ELB_RESULTS}/metadata/job-ids - | jq -r .[] | tr '\n' ' ' `

###############################################################################
# AWS ElasticBLAST suport
GET_SAML_CREDS_TOOL=/net/snowman/vol/export4/blastqa/blastsoft_dev_setup_dir/get_saml_credential.sh
# 8 hours
creds.sh: export DURATION=28800
creds.sh:
	[ -f ~/.aws/credentials ] && mv ~/.aws/credentials ~/.aws/credentials~ || true
	source setenv.sh && ${GET_SAML_CREDS_TOOL} | tee $@

# Use to generate an AWS credentials file for the jump account. 
# Pre-requisite, the ROLEARN and PRINCIPLEARN environment variables are set in setenv.sh
# How to use: `make -B aws-credentials`; if output looks OK, copy output file to ~/.aws (see output below)
aws-credentials:
	@source setenv.sh && ${GET_SAML_CREDS_TOOL} ${USER} | \
		sed 's/export AWS_ACCESS_KEY_ID/aws_access_key_id/;s/export AWS_SECRET_ACCESS_KEY/aws_secret_access_key/;s/export AWS_SESSION_TOKEN/aws_session_token/;s/export AWS_DEFAULT_REGION/region/;s/"//g;1a[default]' | \
		egrep -v AWS_ACCT\|AWS_CRED_TIME | tee $@
	@source setenv.sh && printenv ROLEARN | awk -F / '{print "["$$NF"]"}' | tee -a $@
	#@echo role_arn = arn:aws:iam::823214259253:role/AWS-RESEARCH-BLAST | tee -a $@
	@echo role_arn = arn:aws:iam::414262389673:role/AWS-RESEARCH-BLAST | tee -a $@
	@echo source_profile = default | tee -a $@
	@grep ^region $@ | tee -a $@
	cp -pv --backup=numbered $@ ~/.aws/credentials
	echo "export AWS_PROFILE=AWS-RESEARCH-BLAST"
	echo "unset AWS_CRED_TIME AWS_ACCT AWS_SESSION_TOKEN AWS_DEFAULT_REGION AWS_SECRET_ACCESS_KEY AWS_ACCESS_KEY_ID"

.PHONY: eks-credentials
eks-credentials:
	aws eks update-kubeconfig --region ${ELB_AWS_REGION} --name ${ELB_CLUSTER_NAME}

.PHONY: aws-limits
aws-limits: ${VENV} creds.sh
	for s in CloudFormation S3 EC2 VPC; do \
		source ${VENV}/bin/activate && source creds.sh && awslimitchecker -S $$s -u; \
		source ${VENV}/bin/activate && source creds.sh && awslimitchecker -S $$s -l; \
	done

clouseau:
	[ -d $@ ] || git clone https://github.com/cfpb/clouseau

clouseau_venv: clouseau
	[ -d $@ ] || virtualenv -p python2.7 $@
	source $@/bin/activate && pip install -r $</requirements.txt

REPO_URL=ssh://git@bitbucket.be-md.ncbi.nlm.nih.gov:9418/blast/elastic-blast.git
.PHONY: scrub-code
scrub-code: clouseau_venv
	source $</bin/activate && \
		PYTHONPATH=${PYTHONPATH}:${PWD}/clouseau clouseau/bin/clouseau -h
	source $</bin/activate && \
		PYTHONPATH=${PYTHONPATH}:${PWD}/clouseau clouseau/bin/clouseau_thin -h
	source $</bin/activate && \
		PYTHONPATH=${PYTHONPATH}:${PWD}/clouseau clouseau/bin/clouseau \
			-u ${REPO_URL} -o json \
			--patterns clouseau/clouseau/patterns/default.txt

.PHONY: results2clustername
results2clustername:
	./share/tools/results2clustername.sh ${ELB_RESULTS}
