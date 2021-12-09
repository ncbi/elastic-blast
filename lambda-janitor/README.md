ElasticBLAST Janitor lambda function
====================================

The code in this directory encapsulates functionality to support automatic shutdown in
ElasticBLAST for AWS.

Overview
--------

The ElasticBLAST janitor in AWS is implemented as a CloudFormation stack which
is nested inside the main ElasticBLAST CloudFormation stack.

The ElasticBLAST janitor CloudFormation stack must be deployed to a publicly
accessible S3 bucket. It refers to a Zip archive containing the code to run
the ElasticBLAST janitor. This Zip archive must also be deployed to a publicly
accessible S3 bucket.

The ElasticBLAST janitor CloudFormation stack contains 2 sets of resources:

1. CopyZips resources: these copy the Zip archive containing the ElasticBLAST
   janitor code from its public location to a temporary bucket created for the
   ElasticBLAST invocation.
2. ElasticBLAST janitor: lambda function, execution role, permission and event rule to 
   enable, schedule and run the ElasticBLAST janitor functionality.

Implementation
--------------

The lambda function code resides in `lambda_elb.py`, though the core code is
in the `elastic_blast` Python module. This lambda function and its
dependencies are deployed to S3 as a Zip archive (see
`elasticblast-janitor-lambda-deployment.zip Makefile` target).

N.B: The `create-admin-role STACK_NAME=elasticblast` creates a CloudFormation
stack with the necessary role for the nested CloudFormation stack to execute.

Maintainer instructions
-----------------------

* Creating the admin role needed to run the janitor: `make create-lambda-role`
* Testing the janitor function in the local host: `make -C.. aws-janitor-smoke-test`
* Testing lambda function code in isolation: `make test-lambda`. Be sure to
  refresh or set the `VENV and ELB_RESULTS Makefile` variables accordingly.
* Deploying lambda standalone function: `make deploy`
* Remove lambda standalone function: `make undeploy`
* Test lambda function deployed via CLI: `make invoke`
* Deploy cloudformation stack for janitor: `make upload-template`
* Deploy to production: `make deploy-to-production`

