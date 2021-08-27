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

"""
Module elastic_blast.split

Split FASTA file into smaller chunks

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import os
import io
from .filehelper import open_for_write, get_error
from typing import Union, List, Iterable, TextIO, Tuple
from .constants import ELB_QUERY_BATCH_FILE_PREFIX

def make_full_name(out_path, nchunk, suffix):
    """ Generate full name for chunk in a uniform manner """
    return os.path.join(out_path, f'{ELB_QUERY_BATCH_FILE_PREFIX}{nchunk:03d}.{suffix}')


def write_chunk(out_path, nchunk, buffer) -> str:
    """ Write buffer into a batch file, return file name """
    full_name = make_full_name(out_path, nchunk, 'fa')
    with open_for_write(full_name) as outf:
        outf.write(''.join(buffer))
    return full_name


class FASTAReader():
    """ Class for reading single file with FASTA sequences and cutting
    into chunks (batches) of length no longer than threshold, if possible.
    Sequences longer than threshold are written in their own chunks without
    breaks mid-sequence.
    """
    def __init__(self, f: Union[Iterable[TextIO], TextIO], batch_len: int,
                 out_path: str):
        """Initialize an object
        Arguments:
            f: Open file handle or stream or an Iterable of open file handles
               or streams.
            batch_len: Batch length in bases/residues
            out_path: Output directory to save query batches
        """
        self.file: Union[Iterable[TextIO], TextIO]
        if isinstance(f, io.TextIOBase):
            self.file = [f]
        else:
            self.file = f
        self.batch_len = batch_len
        self.out_path = out_path
        self.queries: List[str] = []

        self.nchunk = 0
        self.buffer: List[str] = []
        self.seq_buffer: List[str] = []
        self.total_count = 0 # count of base/residue in all processed files
        self.chunk_count = 0 # running base/residue count for chunk
        self.seq_count   = 0 # base/residue counter in current sequence

    def process_chunk(self):
        if not self.buffer: return
        query_fqn = write_chunk(self.out_path, self.nchunk, self.buffer)
        self.queries.append(query_fqn)
        self.nchunk += 1
        self.buffer = []
        self.total_count += self.chunk_count
        self.chunk_count = 0

    def process_new_sequence(self):
        if self.chunk_count + self.seq_count > self.batch_len:
            self.process_chunk()
            self.buffer = self.seq_buffer
            self.chunk_count = self.seq_count
        else:
            self.buffer += self.seq_buffer
            self.chunk_count += self.seq_count
        self.seq_buffer = []
        self.seq_count  = 0

    def read_and_cut(self) -> Tuple[int, List[str]]:
        """ Raed a stream, parse it as FASTA, and write sequences into
        batches approximately of batch_len size.
        Return the total number
        of bases/residues in the input and list of query files written
        """
        nline = 0
        for f in self.file:
            for line in f:
                nline += 1
                if not line: continue
                if line[0] == '>':
                    self.process_new_sequence()
                else:
                    self.seq_count += len(line) - 1
                self.seq_buffer.append(line)
            if len(self.seq_buffer) and not self.seq_buffer[-1].endswith('\n'):
                self.seq_buffer.append('\n')
        self.process_new_sequence()
        self.process_chunk()
        if not nline:
            error = get_error(f)
            if error:
                raise FileNotFoundError(error)
            raise Exception("Empty input file")
        return self.total_count, self.queries
