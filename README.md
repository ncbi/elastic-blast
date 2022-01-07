ElasticBLAST
============

[![Anaconda-Server Badge](https://anaconda.org/bioconda/elastic-blast/badges/version.svg)](https://anaconda.org/bioconda/elastic-blast)
[![Anaconda-Server Badge](https://anaconda.org/bioconda/elastic-blast/badges/latest_release_date.svg)](https://anaconda.org/bioconda/elastic-blast)
[![Anaconda-Server Badge](https://anaconda.org/bioconda/elastic-blast/badges/downloads.svg)](https://anaconda.org/bioconda/elastic-blast)
[![Anaconda-Server Badge](https://anaconda.org/bioconda/elastic-blast/badges/installer/conda.svg)](https://conda.anaconda.org/bioconda)

[![PyPI version](https://badge.fury.io/py/elastic-blast.svg)](https://badge.fury.io/py/elastic-blast)

ElasticBLAST is a cloud-based tool to perform your BLAST searches faster and make you more effective.

ElasticBLAST is ideal for users who have a large number (thousands or more) of queries to BLAST or who prefer to use cloud infrastructure for their searches.  It can run BLAST searches that cannot be done on [NCBI WebBLAST](https://blast.ncbi.nlm.nih.gov) and runs them more quickly than stand-alone [BLAST+](https://www.ncbi.nlm.nih.gov/books/NBK279690/).

ElasticBLAST speeds up your work by distributing your BLAST+ searches across multiple cloud instances. The ability to scale resources in this way allows larger numbers of queries to be searched in a shorter time than you could with BLAST+ on a single host.

The National Center for Biotechnology Information ([NCBI](https://www.ncbi.nlm.nih.gov)), part of the National Library of
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

End-user documentation
----------------------

Please visit https://blast.ncbi.nlm.nih.gov/doc/elastic-blast/

How to get ElasticBLAST
-----------------------

There are several ways to obtain ElasticBLAST, please select the one that is
most suitable to you:

* [Installation from PyPI.org][1]
* [Installation from BioConda][2]
* [Installation for the AWS Cloud Shell][3]
* [Installation for the GCP Cloud Shell][4]

Developer information
---------------------

### How to build ElasticBLAST

    make elastic-blast

### Requirements for building ElasticBLAST

In addition to the requirements listed in the [documentation][5], the [AWS Command Line Interface][6] is required.


[1]: https://blast.ncbi.nlm.nih.gov/doc/elastic-blast/tutorials/pypi-install.html#tutorial-pypi
[2]: https://blast.ncbi.nlm.nih.gov/doc/elastic-blast/tutorials/conda-install.html#tutorial-conda
[3]: https://blast.ncbi.nlm.nih.gov/doc/elastic-blast/quickstart-aws.html#get-elasticblast
[4]: https://blast.ncbi.nlm.nih.gov/doc/elastic-blast/quickstart-gcp.html#get-elasticblast
[5]: https://blast.ncbi.nlm.nih.gov/doc/elastic-blast/requirements.html
[6]: https://aws.amazon.com/cli/
