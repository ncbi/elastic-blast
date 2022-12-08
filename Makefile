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

VENV?=.env

PYTHON_SRC=$(shell find src/elastic_blast bin -type f -name "*.py" ! -path "*eggs*" ! -path "*${VENV}*" ! -name __init__.py ! -path "*.tox*" ! -path "*coverage*" ! -path "*cache*" ! -path "./build*")
YAML_TEMPLATES=$(shell find src/elastic_blast/templates -type f)

all: elastic-blast

#############################################################################
# build targets

PYTHON_VERSION=3
blast-tuner: ${PYTHON_SRC} ${VENV}
	source ${VENV}/bin/activate && pex --disable-cache . -r requirements/base.txt --python=python${PYTHON_VERSION} -c $@.py -o $@
	-./$@ --version

elastic-blast: ${PYTHON_SRC} ${YAML_TEMPLATES} ${VENV} validate-cf-templates
	source ${VENV}/bin/activate && pex --python-shebang='/usr/bin/env python3' --disable-cache . -r requirements/base.txt --python=python${PYTHON_VERSION} -c $@ -o $@
	-./$@ --version

elastic-blast3.9: ${PYTHON_SRC} ${YAML_TEMPLATES} ${VENV} validate-cf-templates
	source ${VENV}/bin/activate && pex --disable-cache . -r requirements/base.txt --python=python3.9 -c elastic-blast -o $@
	-./$@ --version

elastic-blast3.8: ${PYTHON_SRC} ${YAML_TEMPLATES} ${VENV} validate-cf-templates
	source ${VENV}/bin/activate && pex --disable-cache . -r requirements/base.txt --python=python3.8 -c elastic-blast -o $@
	-./$@ --version

elastic-blast3.7: ${PYTHON_SRC} ${YAML_TEMPLATES} ${VENV} validate-cf-templates
	source ${VENV}/bin/activate && pex --disable-cache . -r requirements/base.txt --python=python3.7 -c elastic-blast -o $@
	-./$@ --version

%.md5: %
	md5sum $< >$@

#############################################################################
# Python support

${VENV}: requirements/base.txt requirements/test.txt
	[ -d ${VENV} ] || virtualenv -p python3 $@
	source ${VENV}/bin/activate && pip3 install -qe . -r requirements/test.txt
	source ${VENV}/bin/activate && python3 setup.py install_data

#############################################################################
# AWS support

AWS_ACCOUNT=$(shell aws sts get-caller-identity --output json | jq -r .Account)
iam-policy.json: share/etc/elastic-blast-aws-iam-policy.json.template
	AWS_ACCOUNT=${AWS_ACCOUNT} envsubst < $< > $@

.PHONY: validate-iam-policy
validate-iam-policy: iam-policy.json
	#-AWS_PAGER='' aws accessanalyzer validate-policy --no-paginate --policy-document file://$< --policy-type IDENTITY_POLICY
	-AWS_PAGER='' aws accessanalyzer validate-policy --no-paginate --policy-document file://$< --policy-type RESOURCE_POLICY

.PHONY: validate-cf-templates
validate-cf-templates: 
	AWS_PAGER='' aws --region us-east-1 cloudformation validate-template --template-body file://src/elastic_blast/templates/elastic-blast-cf.yaml
	AWS_PAGER='' aws --region us-east-1 cloudformation validate-template --template-body file://src/elastic_blast/templates/elastic-blast-janitor-cf.yaml
	AWS_PAGER='' aws --region us-east-1 cloudformation validate-template --template-body file://src/elastic_blast/templates/cloudformation-admin-iam.yaml

.PHONY: cfn-lint
cfn-lint: src/elastic_blast/templates/elastic-blast-cf.yaml ${VENV}
	source ${VENV}/bin/activate && cfn-lint -t $<

#############################################################################
# Testing targets

.PHONY: pylint
pylint: ${VENV}
	if [ ! -z "${TEAMCITY_PROJECT_NAME}" ]; then ARGS="--output-format=teamcity.pylint_reporter.TeamCityReporter"; fi; \
	source ${VENV}/bin/activate && pylint --rcfile .pylintrc $$ARGS ${PYTHON_SRC}

.PHONY: mypy
mypy: ${VENV}
	source ${VENV}/bin/activate && mypy src/elastic_blast/

.PHONY: yamllint
yamllint: ${VENV}
	source ${VENV}/bin/activate && \
		yamllint -d share/etc/yamllint-config.yaml src/elastic_blast/templates/elastic-blast-cf.yaml
	source ${VENV}/bin/activate && \
		yamllint -d share/etc/yamllint-config.yaml src/elastic_blast/templates/storage-gcp.yaml
	source ${VENV}/bin/activate && \
		yamllint -d share/etc/yamllint-config.yaml src/elastic_blast/templates/storage-gcp-ssd.yaml
	source ${VENV}/bin/activate && \
		yamllint -d share/etc/yamllint-config.yaml src/elastic_blast/templates/pvc-*.yaml.template
	source ${VENV}/bin/activate && \
		yamllint -d share/etc/yamllint-config.yaml src/elastic_blast/templates/job-init-*
	source ${VENV}/bin/activate && \
		yamllint -d share/etc/yamllint-config.yaml src/elastic_blast/templates/blast-batch-job*

