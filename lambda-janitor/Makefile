# Makefile for ElasticBLAST Janitor module for AWS
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Fri Sep 17 10:04:25 EDT 2021

SHELL=/bin/bash
.PHONY: all

REGION?=us-east-1
STACK_NAME?=elasticblast-${USER}

# Bucket where lambda will be deployed and the nested stack stored
ifeq (ncbi,$(shell hostname -f | grep -o ncbi))
BUCKET?=elb-${USER}
else
BUCKET?=elasticblast-${USER}
endif

CURRENT_DIR=$(shell pwd)
TEMPLATE_DIR=${CURRENT_DIR}/../src/elastic_blast/templates

# For testing purposes
ELB_RESULTS?=s3://elb-camacho/auto-shutdown9
ELB_CLUSTER_NAME?=elasticblast-camacho-3be5e632f

all: create

.PHONY: upload-template
upload-template: ${TEMPLATE_DIR}/elastic-blast-janitor-cf.yaml validate
	aws s3 cp --acl public-read --only-show-errors $< s3://${BUCKET}/templates/

# This role is required to deploy the nested stack
.PHONY: create-admin-role
create-admin-role:
	aws cloudformation describe-stacks --stack-name ${STACK_NAME}-admin-role >& /dev/null || \
		(aws cloudformation create-stack --stack-name ${STACK_NAME}-admin-role --region ${REGION} \
			--template-body file://${TEMPLATE_DIR}/cloudformation-admin-iam.yaml \
			--parameters ParameterKey=Owner,ParameterValue=${USER} \
			--capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
			--disable-rollback --output text && \
		time aws cloudformation wait stack-create-complete --stack-name ${STACK_NAME}-admin-role --region ${REGION})

.PHONY: print-admin-role-arn
print-admin-role-arn:
	aws cloudformation describe-stacks --stack-name ${STACK_NAME}-admin-role --region ${REGION} --query "Stacks[0].Outputs[?OutputKey=='CFNAdminRoleArn'].OutputValue" --output text

.PHONY: create
create: upload-template create-admin-role
	aws cloudformation create-stack --stack-name ${STACK_NAME}-demo-stack --region ${REGION} \
		--template-body file://janitor-test-stack.yaml \
		--parameters ParameterKey=Owner,ParameterValue=${USER} \
		  ParameterKey=JanitorSchedule,ParameterValue="cron(*/5 * * * ? *)" \
		  ParameterKey=JanitorLambdaDeploymentS3Bucket,ParameterValue="${BUCKET}" \
		  ParameterKey=JanitorLambdaDeploymentS3Key,ParameterValue="functions/" \
		  ParameterKey=ElbResults,ParameterValue="${ELB_RESULTS}" \
		  ParameterKey=JanitorTemplateUrl,ParameterValue=https://${BUCKET}.s3.amazonaws.com/templates/elastic-blast-janitor-cf.yaml \
		--capabilities "CAPABILITY_NAMED_IAM" "CAPABILITY_AUTO_EXPAND" \
		--role-arn `aws cloudformation describe-stacks --stack-name ${STACK_NAME}-admin-role --region ${REGION} --query "Stacks[0].Outputs[?OutputKey=='CFNAdminRoleArn'].OutputValue" --output text` \
		--disable-rollback --output json

.PHONY: validate
validate:
	AWS_PAGER='' aws --region ${REGION} cloudformation validate-template --template-body file://${TEMPLATE_DIR}/cloudformation-admin-iam.yaml
	AWS_PAGER='' aws --region ${REGION} cloudformation validate-template --template-body file://${TEMPLATE_DIR}/elastic-blast-janitor-cf.yaml
	AWS_PAGER='' aws --region ${REGION} cloudformation validate-template --template-body file://${CURRENT_DIR}/janitor-test-stack.yaml

.PHONY: delete
delete:
	-aws cloudformation delete-stack --region ${REGION} --stack-name ${STACK_NAME}-demo-stack
	-time aws cloudformation wait stack-delete-complete --stack-name ${STACK_NAME}-demo-stack --region ${REGION}
	-aws cloudformation delete-stack --region ${REGION} --stack-name ${STACK_NAME}-admin-role

.PHONY: describe
describe:
	-aws cloudformation describe-stacks --stack-name ${STACK_NAME}-admin-role --region ${REGION}
	-aws cloudformation describe-stacks --stack-name ${STACK_NAME}-demo-stack --region ${REGION}
	-aws s3 ls --recursive s3://${BUCKET}/functions/
	-aws s3 ls --recursive s3://${BUCKET}/templates/
	-ls -l *.zip
	-aws iam list-roles --path-prefix ${ROLE_PATH} --output json
	-aws lambda list-functions --query "Functions[?FunctionName=='${LAMBDA_FNX_NAME}']" --output json

.PHONY: events
events:
	-aws cloudformation describe-stack-events --stack-name ${STACK_NAME}-admin-role --region ${REGION}
	-aws cloudformation describe-stack-events --stack-name ${STACK_NAME}-demo-stack --region ${REGION}


###############################################################################
# Targets for AWS lambda function that invokes elastic-blast

LAMBDA_FNX_NAME=ncbi-elasticblast-janitor
ROLE_NAME=ncbi-elasticblast-janitor-role
ROLE_PATH=/app/ncbi/elasticblast/
PYTHON_RUNTIME=$(shell awk '/Runtime: / {print $$NF}' ${TEMPLATE_DIR}/elastic-blast-janitor-cf.yaml | sort -Vu | head -1)
LAMBDA_TIMEOUT=$(shell awk '/Timeout: / {print $$NF}' ${TEMPLATE_DIR}/elastic-blast-janitor-cf.yaml | sort -nr | head -1 )
LAMBDA_HANDLER=$(shell awk '/Handler: / {print $$NF}' ${TEMPLATE_DIR}/elastic-blast-janitor-cf.yaml | grep -v index.handler )

VENV?=.env
${VENV}: requirements.txt
	[ -d $@ ] || python3 -m venv $@
	source ${VENV}/bin/activate && pip3 install -r $<

.PHONY: test-lambda
test-lambda: export ELB_DRY_RUN=1
test-lambda: export AWS_REGION=${REGION}
test-lambda: ${VENV}
	ELB_RESULTS=${ELB_RESULTS} ELB_CLUSTER_NAME=${ELB_CLUSTER_NAME} ${VENV}/bin/python3 lambda_elb.py

elasticblast-janitor-lambda-deployment.zip: test-lambda
	(cd ${VENV}/lib/${PYTHON_RUNTIME}/site-packages && zip -qr ${CURRENT_DIR}/$@ .)
	zip -g $@ lambda_elb.py
	# https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html
	if [ `du -m $@ | cut -f 1` -gt 50 ]; then echo "ERROR: $@ is larger than 50MB"; exit 1; fi

# The following targets are for testing lambda function on the CLI

.PHONY: create-lambda-role
create-lambda-role:
	[[ `aws iam list-roles --path-prefix ${ROLE_PATH} --output text ` ]] || \
		( aws iam create-role --role-name ${ROLE_NAME} \
			--assume-role-policy-document file://trust-policy.json \
			--path ${ROLE_PATH} \
			--tags Key=Project,Value=BLAST Key=billingcode,Value=elastic-blast Key=Owner,Value=${USER} Key=Name,Value=${ROLE_NAME} && \
		aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole )
	#aws iam list-roles --path-prefix ${ROLE_PATH}

.PHONY: deploy-for-elasticblast
deploy-for-elasticblast: rm-virtual-env elasticblast-janitor-lambda-deployment.zip upload-template
	aws s3 cp --acl public-read --only-show-errors elasticblast-janitor-lambda-deployment.zip s3://${BUCKET}/functions/

.PHONY: rm-virtual-env
rm-virtual-env:
	rm -fr ${VENV}

.PHONY: deploy
deploy: elasticblast-janitor-lambda-deployment.zip create-lambda-role
	[[ `aws lambda list-functions --query "Functions[?FunctionName=='${LAMBDA_FNX_NAME}']" --output text` ]] || \
		aws lambda create-function --function-name ${LAMBDA_FNX_NAME}  \
			--runtime ${PYTHON_RUNTIME} \
			--description "ElasticBLAST janitor lambda function created using CLI" \
			--zip-file fileb://$< \
			--timeout ${LAMBDA_TIMEOUT} \
			--tags Project=BLAST,billingcode=elastic-blast,Owner=${USER},Name=${LAMBDA_FNX_NAME} \
			--handler ${LAMBDA_HANDLER} \
			--role `aws iam list-roles --path-prefix ${ROLE_PATH} --output text --query 'Roles[0].Arn'`

.PHONY: invoke
invoke: deploy
	-aws lambda invoke --function-name ${LAMBDA_FNX_NAME} response1.json --log-type Tail \
		--cli-binary-format raw-in-base64-out \
		--payload '{ "ELB_RESULTS": "s3://elasticblast-${USER}", "ELB_CLUSTER_NAME": "elasticblast-${USER}", "ELB_DRY_RUN": "1" }' --query 'LogResult' --output text |  base64 -d

.PHONY: undeploy
undeploy:
	-aws lambda delete-function --function-name ${LAMBDA_FNX_NAME}
	-aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
	-aws iam delete-role --role-name ${ROLE_NAME}
