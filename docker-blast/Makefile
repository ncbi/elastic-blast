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

# Makefile for building a container with BLAST+, the GCP SDK,
# and AWS Client
#
# Author: Christiam Camacho
# Created: Thu Jun 23 12:24:39 2020

SHELL=/bin/bash
IMG?=ncbi/elb
GCP_IMG?=gcr.io/ncbi-sandbox-blast/${IMG}
AWS_SERVER?=public.ecr.aws/i6v3i0i9
AWS_IMG?=${AWS_SERVER}/elasticblast-elb
AWS_REGION?=us-east-1
VERSION?=1.0.3

ifeq (, $(shell which vmtouch 2>/dev/null))
NOVMTOUCH?=--no-vmtouch
else
ifeq (, $(shell which blastdb_path 2>/dev/null))            # If blastdb_path is not available, vmtouch cannot do its job, so skip it.
NOVMTOUCH?=--no-vmtouch
else
NOVMTOUCH?=
endif
endif

.PHONY: all
all: build check

.PHONY: build
build:
	docker build --build-arg version=${VERSION} -t ${IMG}:${VERSION} .
	docker tag ${IMG}:${VERSION} ${IMG}:latest

.PHONY: publish 
publish: build
	docker push ${IMG}:${VERSION}
	docker push ${IMG}:latest


setup.cfg_cloud:
	rsync -a ../setup.py ../setup.cfg_cloud ../src ../bin ../requirements ${PWD}/
	sed -i~ -e '/^value = $${VERSION}/d;' setup.cfg_cloud
	echo "value = $(shell git describe --tags --abbrev=0)" >> setup.cfg_cloud

.PHONY: clean-local-sources
clean-local-sources:
	rm -rf setup.py setup.cfg_cloud src bin requirements

.PHONY: gcp-build
gcp-build:
	gcloud builds submit --config=cloudbuild.yaml --substitutions=TAG_NAME="${VERSION}",_IMG="${GCP_IMG}" .

.PHONY: aws-build
aws-build:
	gcloud builds submit --config=awscloudbuild.yaml --substitutions=TAG_NAME="${VERSION}",_IMG="${AWS_IMG}",_SERVER="${AWS_SERVER}",_AWS_ECR_PASSWD="`aws ecr-public get-login-password --region ${AWS_REGION}`" .


# Use the targets below to build imges using local elastic-blast sources
.PHONY: gcp-build-from-local-sources
gcp-build-from-local-sources: setup.cfg_cloud
	gcloud builds submit --config=cloudbuild.yaml --substitutions=TAG_NAME="${VERSION}",_IMG="${GCP_IMG}",_DOCKERFILE='Dockerfile-build-from-local-sources' .
	$(MAKE) clean-local-sources

.PHONY: aws-build-from-local-sources
aws-build-from-local-sources: setup.cfg_cloud
	gcloud builds submit --config=awscloudbuild.yaml --substitutions=TAG_NAME="${VERSION}",_IMG="${AWS_IMG}",_SERVER="${AWS_SERVER}",_AWS_ECR_PASSWD="`aws ecr-public get-login-password --region ${AWS_REGION}`",_DOCKERFILE='Dockerfile-build-from-local-sources' .
	$(MAKE) clean-local-sources

.PHONY: gcp-check
gcp-check:
	gcloud builds submit --config test-docker-image-gcp.yaml --substitutions _TAG=$(VERSION),_IMG=${IMG}

.PHONY: aws-check
aws-check:
	gcloud builds submit --config test-docker-image-aws.yaml --substitutions _IMG="${AWS_IMG}:${VERSION}"

.PHONY: clean 
clean:
	-docker image rm ${IMG}:${VERSION} ${IMG}:latest
	${RM} -fr .env

.PHONY: check 
check:
	docker run --rm ${IMG}:${VERSION} update_blastdb.pl --version
	docker run --rm ${IMG}:${VERSION} blastn -version-full
	docker run --rm ${IMG}:${VERSION} blastdb_path -version-full
	docker run --rm ${IMG}:${VERSION} which vmtouch
	docker run --rm ${IMG}:${VERSION} aws --version
	docker run --rm ${IMG}:${VERSION} gcloud --version
	docker run --rm ${IMG}:${VERSION} printenv BLASTDB | grep /blast/blastdb
	docker run --rm ${IMG}:${VERSION} printenv PATH | grep /blast/bin
	docker run --rm ${IMG}:${VERSION} fasta-split --help
	docker run --rm ${IMG}:${VERSION} splitq_download_db_search --version
	docker run --rm ${IMG}:${VERSION} splitq_download_db_search --help

.env: requirements.txt
	[ -d .env ] || python3 -m venv .env
	. .env/bin/activate && python3 -m pip install -r $<

.PHONY: test_python 
test_python: .env
	.env/bin/python3 -m py_compile splitq_download_db_search fasta-split
	.env/bin/python3 ./fasta-split --help
	.env/bin/python3 ./splitq_download_db_search --version
	.env/bin/python3 ./splitq_download_db_search --help
	.env/bin/python3 ./splitq_download_db_search --db nt --source AWS --query q --num-threads 20 \
	                    --program blastn --bucket s3://bucket --db-mol-type nucl \
	                    --taxidlist s3://bucket/taxidlist --params '-outfmt "6 std staxids"'\
	                    --dry-run

# Actual small test, executes in under 7 seconds on a local machine
# 1. AWS cretentials needed to access s3://elasticblast-test
# 2. Due to old coreutils (need 8.30) it can't use /usr/bin/env -S,
#    thus explicit Python so it works on older machines.
# 3. blastdb_path is not always available, flag --no-vmtouch introduced
.PHONY: test_small_run 
test_small_run: .env
	.env/bin/python3 ./splitq_download_db_search --workdir wd_pdbnt_blastn ${NOVMTOUCH} --db pdbnt --source AWS \
	        --query s3://elasticblast-test/queries/e7ebd4c9-d8a3-405c-8180-23b85f1709a7.fa.gz \
			--num-threads 20 --program blastn --bucket s3://elasticblast-test/small-run \
			--db-mol-type nucl --params '-outfmt "6 std staxids"'
	test `aws s3 cp s3://elasticblast-test/small-run/e7ebd4c9-d8a3-405c-8180-23b85f1709a7-blastn-pdbnt.out.gz -|zcat | wc -l` -gt 0
	-aws s3 rm s3://elasticblast-test/small-run/e7ebd4c9-d8a3-405c-8180-23b85f1709a7-blastn-pdbnt.out.gz --only-show-errors
	-rm -rf wd_pdbnt_blastn

.PHONY: test_small_run_no_creds 
test_small_run_no_creds: .env
	. .env/bin/activate; python3 ./splitq_download_db_search --workdir wd_pdbnt_blastn ${NOVMTOUCH} \
	        --db pdbnt --source AWS --no-creds \
	        --query s3://elasticblast-test/queries/e7ebd4c9-d8a3-405c-8180-23b85f1709a7.fa.gz \
			--num-threads 20 --program blastn --bucket s3://non-existent-bucket \
			--db-mol-type nucl --params '-outfmt "6 std staxids"'
	test `zcat wd_pdbnt_blastn/non-existent-bucket/e7ebd4c9-d8a3-405c-8180-23b85f1709a7-blastn-pdbnt.out.gz | wc -l` -gt 0
	du -h wd_pdbnt_blastn
	-rm -rf wd_pdbnt_blastn

.PHONY: test_small_run_no_creds_prot 
test_small_run_no_creds_prot: .env
	. .env/bin/activate; python3 ./splitq_download_db_search --workdir wd_swissprot_blastp ${NOVMTOUCH} \
	        --db swissprot --source AWS --no-creds \
	        --query s3://elasticblast-test/queries/viralmeta.fsa \
			--split-part 1 --num-parts 3992 \
			--num-threads 20 --program blastp --bucket s3://non-existent-bucket \
			--db-mol-type prot --params '-task blastp-fast -evalue 0.01 -outfmt 7'
	test `zcat wd_swissprot_blastp/non-existent-bucket/batch_001-blastp-swissprot.out.gz | wc -l` -gt 0
	du -h wd_swissprot_blastp
	-rm -rf wd_swissprot_blastp

tmp_output:=$(shell mktemp -d)
.PHONY: test_fasta_split_in_n_parts_no_creds
test_fasta_split_in_n_parts_no_creds: .env
	${RM} ${tmp_output}/*
	.env/bin/python3 fasta-split s3://elasticblast-test/queries/viralmeta.fsa -N 100 -o ${tmp_output} --no-creds
	test `ls ${tmp_output}/ | wc -l` -eq 100

.PHONY: test_fasta_split_by_batch_lenght_no_creds
test_fasta_split_by_batch_length_no_creds: .env
	${RM} ${tmp_output}/*
	.env/bin/python3 fasta-split s3://elasticblast-test/queries/viralmeta.fsa -o ${tmp_output} --no-creds
	test `ls ${tmp_output}/ | wc -l` -eq 8

# Test required parameters
.PHONY: test_parameters 
test_parameters: .env
	.env/bin/python3 ./splitq_download_db_search && exit 1 || exit 0

# Test that attempt to use binary file as FASTA fails
.PHONY: test_invalid_query
test_invalid_query: .env
	aws s3 cp test_data/Garbage_query_file.fa s3://elasticblast-test/test-queries/ --only-show-errors
	.env/bin/python3 ./splitq_download_db_search --workdir wd_pdbnt_blastn ${NOVMTOUCH} --db pdbnt --source AWS \
	        --query s3://elasticblast-test/test-queries/Garbage_query_file.fa \
			--num-threads 20 --program blastn --bucket s3://elasticblast-test/small-run \
			--db-mol-type nucl --params '-outfmt "6 std staxids"' && exit 1 || exit 0
	-aws s3 rm s3://elasticblast-test/test-queries/Garbage_query_file.fa --only-show-errors
	-rm -rf wd_pdbnt_blastn

.PHONY: test_non_existent_db 
test_non_existent_db: .env
	.env/bin/python3 ./splitq_download_db_search --workdir wd_pdbnt_blastn ${NOVMTOUCH} \
	        --db invalid_db --db-path s3://invalid-bucket --source AWS \
	        --query s3://elasticblast-test/queries/e7ebd4c9-d8a3-405c-8180-23b85f1709a7.fa.gz \
	        --num-threads 20 --program blastn --bucket s3://elasticblast-test/small-run \
	        --db-mol-type nucl --params '-outfmt "6 std staxids"' && exit 1 || exit 0
	-rm -rf wd_pdbnt_blastn

.PHONY: test_invalid_db 
test_invalid_db: .env
	aws s3 cp test_data/ s3://elasticblast-test/test-db --recursive --exclude '*' --include 'pdbnt.*' --only-show-errors
	.env/bin/python3 ./splitq_download_db_search --workdir wd_pdbnt_blastn ${NOVMTOUCH} \
	        --db-path s3://elasticblast-test/test-db --db pdbnt --source AWS \
	        --query s3://elasticblast-test/queries/e7ebd4c9-d8a3-405c-8180-23b85f1709a7.fa.gz \
	        --num-threads 20 --program blastn --bucket s3://elasticblast-test/small-run \
	        --db-mol-type nucl --params '-outfmt "6 std staxids"' && exit 1 || exit 0
	-aws s3 rm s3://elasticblast-test/test-db/ --recursive --only-show-errors
	-rm -rf wd_pdbnt_blastn

.PHONY: test
test: test_python test_small_run test_parameters test_invalid_query test_non_existent_db test_invalid_db test_small_run_no_creds_prot test_small_run_no_creds test_fasta_split_by_batch_length_no_creds test_fasta_split_in_n_parts_no_creds
