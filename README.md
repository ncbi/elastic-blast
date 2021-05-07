# ElasticBLAST

ElasticBLAST is a cloud-based tool to perform your BLAST searches faster and make you more effective.

ElasticBLAST is ideal for users who have 100,000 or more queries to BLAST and don't want to wait
 for results.  It distributes your queries to machines in the cloud and runs them more quickly than you could with stand-alone BLAST.

The National Center for Biotechnology ([NCBI](https://www.ncbi.nlm.nih.gov)), part of the National Library of
Medicine at the NIH, developed and maintains ElasticBLAST.

The NCBI is making the source code for ElasticBLAST available on GitHub as an
Open Distribution to allow the user community to easily obtain and examine
that code.  GitHub also provides a means for users to report issues and
suggest modifications through pull requests. 

The NCBI will use internal source code control as the repository of record and
push regular releases of the ElasticBLAST
source code to GitHub.  The BLAST developers will work to ensure that
ElasticBLAST continues to function in 
changing environments and, when possible, integrate user feedback into
ElasticBLAST.  Owing to resource constraints, 
they cannot absolutely commit to act on all issue reports, except critical
security vulnerabilities.

## End-user documentation

Please visit https://blast.ncbi.nlm.nih.gov/doc/elastic-blast/

## How to get ElasticBLAST

Please see instructions here:
https://blast.ncbi.nlm.nih.gov/doc/elastic-blast/quickstart-aws.html#get-elasticblast

## How to build ElasticBLAST

`make elastic-blast`

### Requirements for building ElasticBLAST

In addition to the requirements listed in the page below, [AWS Command Line Interface](https://aws.amazon.com/cli/) is required.

https://blast.ncbi.nlm.nih.gov/doc/elastic-blast/requirements.html
