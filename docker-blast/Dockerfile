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

FROM ncbi/blast:2.17.0 as blast
ARG version
LABEL Description="NCBI BLAST" Vendor="NCBI/NLM/NIH" Version=${version} Maintainer=camacho@ncbi.nlm.nih.gov

USER root
WORKDIR /root/

COPY requirements.txt .

RUN apt-get -y -m update && \
    apt-get install -y python3 python3-pip time parallel vmtouch curl wget unzip && \
    pip3 --version && python3 -m pip --version && \
	rm -rf /var/lib/apt/lists/*  

RUN python3 -m pip install --no-cache-dir --upgrade pip && \
    python3 -m pip install --no-cache-dir -r requirements.txt && \
    rm -frv requirements.txt

COPY splitq_download_db_search /blast/bin/
RUN sed -i -e "s/\$VERSION/$version/" /blast/bin/splitq_download_db_search
COPY fasta-split /blast/bin/

CMD ["/bin/bash"]

