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

# Makefile for building a container to run the ElasticBLAST job submission on
# the cloud
#
# Author: Christiam Camacho
# Created: Tue Aug 31 11:29:06 EDT 2021

SHELL=/bin/bash
.PHONY: all pre-check check clean build publish gcp-build gcp-check gcp-clean azure-build

IMG?=ncbi/elasticblast-job-submit
VERSION?=4.0.3.4
ELB_VERSION?=$(shell git describe --tags --abbrev=0)
GCP_PROJECT?=$(shell gcloud config get-value project 2>/dev/null)
GCP_TEST_BUCKET?=gs://elasticblast-test/cloud-job-submission
AWS_REGION?=us-east-1
AWS_SERVER?=public.ecr.aws/ncbi-elasticblast
AWS_IMG?=${AWS_SERVER}/elasticblast-job-submit

# For gcp-test
ELB_GCP_PROJECT?=ncbi-sandbox-blast
ELB_GCP_REGION?=us-east4
ELB_GCP_ZONE?=us-east4-a
ELB_RESULTS?=gs://elasticblast-test
ELB_CLUSTER_NAME?=elb-test-cluster
AZURE_REGISTRY?=elbacr.azurecr.io

all: gcp-build gcp-check

build:
	docker build --build-arg version=${VERSION} -f Dockerfile.gcp -t ${IMG}:${VERSION} .
	docker tag ${IMG}:${VERSION} ${IMG}:latest

publish: build
	docker push ${IMG}:${VERSION}
	docker push ${IMG}:latest

clean:
	-docker image rm ${IMG}:${VERSION} ${IMG}:latest

check:
	-docker run --rm ${IMG}:${VERSION} kubectl version --client=true
	-docker run --rm ${IMG}:${VERSION}

.PHONY: azure-build
azure-build:
	rsync -a ../src/elastic_blast/templates ${PWD}/
	az acr build -f Dockerfile.azure --registry $(AZURE_REGISTRY) --image $(IMG):$(VERSION) .
	rm -fr templates

.PHONY: gcp-build
gcp-build:
	rsync -a ../src/elastic_blast/templates ${PWD}/
	gcloud builds submit --config cloudbuild.yaml --substitutions _VERSION=${VERSION},_IMG=${IMG}

.PHONY: aws-build
aws-build:
	gcloud builds submit --config=awscloudbuild.yaml --substitutions=_DOCKERFILE=Dockerfile.aws,TAG_NAME="${VERSION}",_IMG="${AWS_IMG}",_SERVER="${AWS_SERVER}",_AWS_ECR_PASSWD="`aws ecr-public get-login-password --region ${AWS_REGION}`" .

# Use this target to build an image from your local sources as opposed to those on PyPI.org
.PHONY: aws-build-from-local-sources
aws-build-from-local-sources:
	rsync -a ../setup.py ../setup.cfg_cloud ../src ../bin ../requirements ${PWD}/
	sed -i~ -e '/^value = $${VERSION}/d;' setup.cfg_cloud
	echo "value = ${ELB_VERSION}" >> setup.cfg_cloud
	-gcloud builds submit --config awscloudbuild.yaml --substitutions _SERVER=${AWS_SERVER},TAG_NAME=${VERSION},_IMG=${AWS_IMG},_DOCKERFILE=Dockerfile-build-from-local-sources.aws,_AWS_ECR_PASSWD="`aws ecr-public get-login-password --region ${AWS_REGION}`"
	rm -fr src bin requirements setup.cfg_cloud setup.py

.PHONY: aws-check
aws-check:
	gcloud builds submit --config awscloudrun.yaml --substitutions _IMG="${AWS_IMG}:${VERSION}",_ELB_RESULTS="${ELB_RESULTS}",_ELB_CLUSTER_NAME="${ELB_CLUSTER_NAME}"

gcp-clean:
	-gcloud container images delete gcr.io/${GCP_PROJECT}/${IMG}:${VERSION}

.PHONY: gcp-check
gcp-check:
	-gcloud container images list --repository=gcr.io/${GCP_PROJECT}/${IMG}
	-gcloud container images list-tags gcr.io/${GCP_PROJECT}/${IMG}
	-gcloud container images describe gcr.io/${GCP_PROJECT}/${IMG}:latest
	-gcloud container images describe gcr.io/${GCP_PROJECT}/${IMG}:${VERSION}
	gcloud builds submit --timeout=120 --config cloudrun.yaml --substitutions _IMG="gcr.io/${GCP_PROJECT}/${IMG}:${VERSION}",_ELB_GCP_PROJECT="${ELB_GCP_PROJECT}",_ELB_GCP_ZONE="${ELB_GCP_ZONE}",_ELB_RESULTS="${ELB_RESULTS}",_ELB_CLUSTER_NAME="${ELB_CLUSTER_NAME}"

gcp-list-tagless-images:
	gcloud container images list-tags gcr.io/${GCP_PROJECT}/${IMG} \
		--filter='-tags:*' --format="get(digest)"
