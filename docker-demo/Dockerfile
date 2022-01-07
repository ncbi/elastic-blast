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

FROM google/cloud-sdk:slim

ARG version
ARG username=masterblaster
ARG grpname=blast

LABEL Description="NCBI ElasticBLAST"
LABEL Version=${version}
LABEL Vendor="NCBI/NLM/NIH"
LABEL Maintainer=camacho@ncbi.nlm.nih.gov

USER root

COPY requirements.txt .

RUN apt-get -y -m update && \
    apt-get install -y python3 kubectl && \
    pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir -r requirements.txt && \
    rm -rf /var/lib/apt/lists/* requirements.txt

RUN groupadd -r ${grpname} && \
    useradd --no-log-init -r -g ${grpname} ${username} && \
    mkdir -vp /home/${username} && \
    chown -Rc ${username}:${grpname} /home/${username}

USER ${username}
WORKDIR /home/${username}

COPY --chown=${username}:${grpname} Makefile-demo.mk Makefile
COPY --chown=${username}:${grpname} README.md *.ini /home/${username}/

CMD ["/bin/bash"]

