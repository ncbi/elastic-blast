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

PROD_BUCKET=elb-camacho
LAMBDA_FNX_NAME=ncbi-elasticblast-janitor
ROLE_NAME=ncbi-elasticblast-janitor-role
ROLE_PATH=/app/ncbi/elasticblast/
# This is a deployment package, it cannot exceed 50MB
LAMBDA_FNX_ARCHIVE=elasticblast-janitor-lambda-deployment.zip
PYTHON_RUNTIME=$(shell awk '/Runtime: / {print $$NF}' ${TEMPLATE_DIR}/elastic-blast-janitor-cf.yaml | sort -Vu | head -1)
LAMBDA_TIMEOUT=$(shell awk '/Timeout: / {print $$NF}' ${TEMPLATE_DIR}/elastic-blast-janitor-cf.yaml | sort -nr | head -1 )
LAMBDA_HANDLER=$(shell awk '/Handler: / {print $$NF}' ${TEMPLATE_DIR}/elastic-blast-janitor-cf.yaml | grep -v index.handler )
LAMBDA_MEMORY=$(shell awk '/MemorySize: / {print $$NF}' ${TEMPLATE_DIR}/elastic-blast-janitor-cf.yaml )

VENV?=.env
REQUIREMENTS?=requirements.txt
${VENV}: ${REQUIREMENTS}
	[ -d $@ ] || python3 -m venv $@
	source ${VENV}/bin/activate && pip3 install -r $<

test-lambda-locally:
	rm -fr .env-testing
	make VENV=.env-testing REQUIREMENTS=requirements-for-testing.txt ${LAMBDA_FNX_ARCHIVE}

test-lambda-locally-dry-run:
	rm -fr .env-testing
	make VENV=.env-testing REQUIREMENTS=requirements-for-testing.txt ${LAMBDA_FNX_ARCHIVE} ELB_DRY_RUN=1


.PHONY: test-lambda
test-lambda: export AWS_REGION=${REGION}
test-lambda: ${VENV}
	ELB_RESULTS=${ELB_RESULTS} ${VENV}/bin/python3 lambda_elb.py

${LAMBDA_FNX_ARCHIVE}: test-lambda
	(cd ${VENV}/lib/${PYTHON_RUNTIME}/site-packages && zip -qr ${CURRENT_DIR}/$@ .)
	zip -g $@ lambda_elb.py
	# https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html
	@if [ `du -m $@ | cut -f 1` -gt 50 ]; then echo "ERROR: $@ is larger than 50MB"; exit 1; fi

# The following targets are for testing lambda function on the CLI

.PHONY: create-lambda-role
create-lambda-role:
	[[ `aws iam list-roles --path-prefix ${ROLE_PATH} --output text ` ]] || \
		( aws iam create-role --role-name ${ROLE_NAME} \
			--assume-role-policy-document file://trust-policy.json \
			--path ${ROLE_PATH} \
			--tags Key=Project,Value=BLAST Key=billingcode,Value=elastic-blast Key=Owner,Value=${USER} Key=Name,Value=${ROLE_NAME} && \
		aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole && \
		aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AmazonVPCReadOnlyAccess && \
		aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess && \
		aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AWSBatchFullAccess && \
		aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess && \
		aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/IAMFullAccess && \
		aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AWSCloudFormationFullAccess \
		)
	#aws iam list-roles --path-prefix ${ROLE_PATH}

# THIS TARGET UPDATES PRODUCTION ELASTIC BLAST!!
.PHONY: deploy-to-production
deploy-to-production: rm-virtual-env ${LAMBDA_FNX_ARCHIVE} upload-template
	aws s3 cp --acl public-read --only-show-errors ${LAMBDA_FNX_ARCHIVE} s3://${BUCKET}/functions/

# This target updates the lambda function created via CLI used for testing 
.PHONY: update-lambda-deployment-dry-run
update-lambda-deployment-dry-run: ${LAMBDA_FNX_ARCHIVE}
	aws lambda update-function-code --function-name ${LAMBDA_FNX_NAME} \
		--zip-file fileb://${LAMBDA_FNX_ARCHIVE} --no-publish \
		--dry-run 

# This target updates the lambda function created via CLI used for testing 
.PHONY: update-lambda-deployment
update-lambda-deployment: ${LAMBDA_FNX_ARCHIVE}
	aws lambda update-function-code --function-name ${LAMBDA_FNX_NAME} \
		--zip-file fileb://${LAMBDA_FNX_ARCHIVE} --no-publish
	aws lambda wait function-updated --function-name ${LAMBDA_FNX_NAME}
	aws lambda update-function-configuration --function-name ${LAMBDA_FNX_NAME} \
		--runtime ${PYTHON_RUNTIME} \
		--timeout ${LAMBDA_TIMEOUT} \
		--memory-size ${LAMBDA_MEMORY}

################################################################################
## Alias/Version management
.PHONY: list-versions
list-versions: list-aliases
	aws lambda list-versions-by-function --function-name ${LAMBDA_FNX_NAME} --output json

.PHONY: list-latest-object-versions
list-latest-object-versions:
	-aws s3api list-object-versions --bucket ${BUCKET} --prefix templates/elastic-blast-janitor-cf.yaml --query 'Versions[?IsLatest].[VersionId]' --output text
	-aws s3api list-object-versions --bucket ${BUCKET} --prefix functions/${LAMBDA_FNX_ARCHIVE} --query 'Versions[?IsLatest].[VersionId]' --output text

.PHONY: list-object-versions
list-object-versions:
	-aws s3api list-object-versions --bucket ${BUCKET} --prefix templates/elastic-blast-janitor-cf.yaml --output json
	-aws s3api list-object-versions --bucket ${BUCKET} --prefix functions/${LAMBDA_FNX_ARCHIVE} --output json

.PHONY: create-alias
create-alias:
	[ ! -z "${LAMBDA_FNX_PRODUCTION_VERSION}" ] || { echo "LAMBDA_FNX_PRODUCTION_VERSION environment variable must be defined. Please visit https://console.aws.amazon.com/lambda/home?region=us-east-1#/functions/ncbi-elasticblast-janitor?tab=versions"; exit 1; }
	aws lambda create-alias --function-name ${LAMBDA_FNX_NAME} \
		--description "Production ElasticBLAST Janitor for testing purposes" \
		--name PRODUCTION --function-version ${LAMBDA_FNX_PRODUCTION_VERSION}

.PHONY: publish-version
publish-version:
	[ ! -z "${DESCRIPTION}" ] || { echo "DESCRIPTION environment variable must be defined"; exit 1; }
	aws lambda publish-version --function-name ${LAMBDA_FNX_NAME} \
		--description "${DESCRIPTION}"

.PHONY: list-aliases
list-aliases:
	aws lambda list-aliases --function-name ${LAMBDA_FNX_NAME}
	aws lambda get-alias --function-name ${LAMBDA_FNX_NAME} --name PRODUCTION

.PHONY: rm-virtual-env
rm-virtual-env:
	rm -fr ${VENV}

# This isn't needed for updates! Please see update-lambda-deployment* Makefile targets
.PHONY: deploy
deploy: ${LAMBDA_FNX_ARCHIVE} create-lambda-role
	[[ `aws lambda list-functions --query "Functions[?FunctionName=='${LAMBDA_FNX_NAME}']" --output text` ]] || \
		aws lambda create-function --function-name ${LAMBDA_FNX_NAME}  \
			--runtime ${PYTHON_RUNTIME} \
			--description "ElasticBLAST janitor lambda function created using CLI for TESTING" \
			--zip-file fileb://$< \
			--timeout ${LAMBDA_TIMEOUT} \
			--memory-size ${LAMBDA_MEMORY} \
			--tags Project=BLAST,billingcode=elastic-blast,Owner=${USER},Name=${LAMBDA_FNX_NAME} \
			--handler ${LAMBDA_HANDLER} \
			--role `aws iam list-roles --path-prefix ${ROLE_PATH} --output text --query 'Roles[0].Arn'`

ELB_DRY_RUN?=1
# This invokes the ${LAMBDA_FNX_NAME}. this MUST work before deploying to production (i.e.: deploy-to-production)
.PHONY: invoke
invoke:
	[ -z "${ELB_DRY_RUN}" ] && \
		printf '{ "ELB_RESULTS": "%s" }\n' ${ELB_RESULTS} | jq -Mr . | tee | base64 > ${TMP_OUTPUT} || \
		printf '{ "ELB_RESULTS": "%s", "ELB_DRY_RUN": "1" }\n' ${ELB_RESULTS} | jq -Mr . | tee | base64 > ${TMP_OUTPUT}
	${RM} response.json invoke-output.json
	echo "Request sent to lambda:"
	cat -n ${TMP_OUTPUT}
	aws lambda invoke --function-name ${LAMBDA_FNX_NAME} --invocation-type DryRun response.json
	cat response.json
	${RM} response.json invoke-output.json
	[ -z "${LAMBDA_FNX_PRODUCTION_VERSION}" ] && \
		aws lambda invoke --function-name ${LAMBDA_FNX_NAME} \
			--invocation-type RequestResponse --log-type Tail \
			--payload file://${TMP_OUTPUT} --output json response.json > invoke-output.json || \
		aws lambda invoke --function-name ${LAMBDA_FNX_NAME} \
			--invocation-type RequestResponse --log-type Tail \
			--qualifier ${LAMBDA_FNX_PRODUCTION_VERSION} \
			--payload file://${TMP_OUTPUT} --output json response.json > invoke-output.json
	jq -Mr . invoke-output.json
	jq -Mr .LogResult invoke-output.json | base64 -d
	jq -Mr . response.json

.PHONY: undeploy
undeploy:
	-aws lambda delete-function --function-name ${LAMBDA_FNX_NAME}
	-aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
	-aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AmazonVPCReadOnlyAccess
	-aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess
	-aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AWSBatchFullAccess
	-aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess
	-aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/IAMFullAccess
	-aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AWSCloudFormationFullAccess
	-aws iam delete-role --role-name ${ROLE_NAME}

###############################################################################
# Compares the production deployment with the current sources
TMP_OUTPUT:=$(shell mktemp -t "XXXXXXX.tmp")
TMP_OUTPUT2:=$(shell mktemp -t "XXXXXXX.tmp")
diff:
	aws s3 cp --only-show-errors s3://${PROD_BUCKET}/templates/elastic-blast-janitor-cf.yaml ${TMP_OUTPUT}
	diff ${TMP_OUTPUT} ${TEMPLATE_DIR}/elastic-blast-janitor-cf.yaml
	aws s3 cp --only-show-errors s3://${PROD_BUCKET}/functions/${LAMBDA_FNX_ARCHIVE} ${TMP_OUTPUT2}
	#unzip -l ${TMP_OUTPUT2}
	unzip -p ${TMP_OUTPUT2} lambda_elb.py > ${TMP_OUTPUT}
	diff ${TMP_OUTPUT} lambda_elb.py



