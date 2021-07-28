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

# Makefile for building a container to run an ElasticBLAST demo
#
# Author: Christiam Camacho
# Created: Wed Jun 23 13:32:04 EDT 2021

SHELL=/bin/bash
.PHONY: all pre-check check clean build publish gcp-build gcp-check gcp-clean

IMG?=ncbi/elastic-blast-query-splitting
VERSION?=0.0.1
GCP_PROJECT?=$(shell gcloud config get-value project 2>/dev/null)
AWS_REGION?=us-east-1
AWS_SERVER?=public.ecr.aws/i6v3i0i9
AWS_IMG?=${AWS_SERVER}/elasticblast-query-split

all: gcp-build gcp-check

build:
	docker build --build-arg version=${VERSION} -t ${IMG}:${VERSION} .
	docker tag ${IMG}:${VERSION} ${IMG}:latest

publish: build
	docker push ${IMG}:${VERSION}
	docker push ${IMG}:latest

clean:
	-docker image rm ${IMG}:${VERSION} ${IMG}:latest

check:
	-docker run --rm ${IMG}:${VERSION} aws --version
	docker run --rm ${IMG}:${VERSION} fasta-split --help
	-docker run --rm ${IMG}:${VERSION} elastic-blast.py --version

gcp-build:
	gcloud builds submit --config cloudbuild.yaml --substitutions _VERSION=${VERSION},_IMG=${IMG}

gcp-clean:
	-gcloud container images delete gcr.io/${GCP_PROJECT}/${IMG}:${VERSION}

gcp-check:
	-gcloud container images list --repository=gcr.io/${GCP_PROJECT}/${IMG}
	-gcloud container images list-tags gcr.io/${GCP_PROJECT}/${IMG}
	-gcloud container images describe gcr.io/${GCP_PROJECT}/${IMG}:latest
	-gcloud container images describe gcr.io/${GCP_PROJECT}/${IMG}:${VERSION}
	gcloud builds submit --config test-cloudbuild.yaml --substitutions _TAG=$(VERSION),_IMG=${IMG}

gcp-list-tagless-images:
	gcloud container images list-tags gcr.io/${GCP_PROJECT}/${IMG} \
		--filter='-tags:*' --format="get(digest)"

.PHONY: aws-build
aws-build:
	gcloud builds submit --config=awscloudbuild.yaml --substitutions=TAG_NAME="${VERSION}",_IMG="${AWS_IMG}",_SERVER="${AWS_SERVER}",_AWS_ECR_PASSWD="`aws ecr-public get-login-password --region us-east-1`" .

# This command needs to be run on an instance with docker installed. First build the image using "make build"
ECR_REPO=?65123123.dkr.ecr.us-east-1.amazonaws.com
.PHONY: publish-to-ecr
publish-to-ecr:
	aws ecr get-login --no-include-email --region ${AWS_REGION} | tee docker-login.sh
	chmod +x docker-login.sh
	./docker-login.sh && docker tag ${IMG}:${VERSION} ${ECR_REPO}/${IMG}:${VERSION}

.PHONY: ecr-list
ecr-list:
	aws ecr list-images --repository ${IMG}

# N.B. Image scanning is free per https://aws.amazon.com/about-aws/whats-new/2019/10/announcing-image-scanning-for-amazon-ecr/
.PHONY: ecr-create
ecr-create:
	aws ecr create-repository --repository-name ${IMG} --region ${AWS_REGION} \
		--image-scanning-configuration scanOnPush=true \
		--tags Key=Project,Value=BLAST Key=billingcode,Value=elastic-blast Key=Owner,Value=${USER} | tee ecr-create.json
