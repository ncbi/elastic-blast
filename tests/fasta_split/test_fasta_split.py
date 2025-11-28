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
test_fasta_split.py - unit test for fasta_split utility

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import unittest
import os, subprocess, shutil, io, hashlib, re
import tempfile

TEST_CMD = 'fasta_split.py'

TEST_DIR = os.path.join(os.path.dirname(__file__), 'testdata')
TEST_FILE = 'e7ebd4c9-d8a3-405c-8180-23b85f1709a7.fa.gz'
TEST_URL = os.getenv('TEST_URL')
TEST_FILE_GZ = 'actually_gzipped_fasta.fa'
TEST_FILE_NOT_GZ = 'actually_not_zipped_fasta.fa.gz'
TEST_FILE_NOT_TAR = 'actually_not_tarred_fasta.fa.tar'
TEST_FILE_NOT_EXIST = 'non_existent_input_file.fa'
TEST_FILE_EMPTY = 'empty_file.fa'
TEST_TMPL = 'test_template'
TEST_INV_TMPL = 'non_existent_template'
TEST_MANIFEST_AT_ROOT = '/manifest.txt'
TEST_RESULTS = 'abra1235176cada25312bra'
TEST_BATCH_LENGTH = os.getenv('TEST_BATCH_LENGTH', '10000')


def read_fasta(d, res, seq_len):
    defline = None
    hash = hashlib.sha256()
    count = 0
    for line in d.split('\n'):
        if line and line[0] == '>':
            if defline:
                res[defline] = hash.digest()
                hash = hashlib.sha256()
                seq_len.append(count)
                count = 0
            defline = line
        else:
            hash.update(line.encode())
            count += len(line)
    if defline:
        res[defline] = hash.digest()
        seq_len.append(count)


re_yaml_name = re.compile(r'batch_([0-9]+)\.yaml')

class TestSplitResultMatchesOriginal(unittest.TestCase):
    def setUp(self):
        self.test_file = TEST_DIR+'/'+TEST_FILE if not TEST_URL else TEST_URL
        self.test_tmpl = TEST_DIR+'/'+TEST_TMPL
        self.test_res_dir = tempfile.mkdtemp()
        self.batch_dir = os.path.join(self.test_res_dir, 'batches')
        self.job_dir   = os.path.join(self.test_res_dir, 'jobs')
        self.value_of_test_substitution_variable = 'Some_gibberish_to_test_substitution_variable'
        proc = subprocess.run([TEST_CMD, self.test_file, '-l', TEST_BATCH_LENGTH,
            '-o', self.batch_dir, '-j', self.job_dir, '-t', self.test_tmpl,
            '-r', TEST_RESULTS,
            '-s', f'SOME_EXTRA_SUBSTITUTION_VARIABLE_WE_PASS_AS_ARGUMENT={self.value_of_test_substitution_variable}'],
            stdout=subprocess.DEVNULL)
        self.assertEqual(proc.returncode, 0)
        proc_args = []
        if self.test_file[:5] == 'gs://':
            proc_args = 'gsutil cat {}'
        elif self.test_file[:4] == 'http':
            proc_args = 'curl -s {}'
        else:
            proc_args = 'cat {}'
        if self.test_file[-3:] == '.gz':
            proc_args += '| gzip -d'
        proc_args = proc_args.format(self.test_file)
        proc = subprocess.run(proc_args, shell=True, stdout=subprocess.PIPE)
        self.orig_text = proc.stdout.decode()

    def tearDown(self):
        shutil.rmtree(self.test_res_dir)

    def test_split(self):
        # Test that contents of split files together comprise
        # original file
        res_orig = {}
        seq_len_orig = []
        read_fasta(self.orig_text, res_orig, seq_len_orig)
        res_split = {}
        total_len = 0
        test_batch_length = int(TEST_BATCH_LENGTH)
        for fn in os.listdir(self.batch_dir):
            with open(os.path.join(self.batch_dir, fn)) as f:
                seq_len = []
                read_fasta(f.read(), res_split, seq_len)
                # Check that if more than one sequence in batch its length is
                # less than the limit
                batch_len = sum(seq_len)
                if len(seq_len) > 1:
                    self.assertTrue(batch_len <= test_batch_length)
                total_len += batch_len
        self.assertEqual(res_orig, res_split)
        self.assertEqual(sum(seq_len_orig), total_len)
        # Test that job files variables expanded properly
        for fn in os.listdir(self.job_dir):
            with open(os.path.join(self.job_dir, fn)) as f:
                mo = re_yaml_name.match(fn)
                query_num = mo.group(1)
                text_actual = f.read()
                text_compare = f"""\
{query_num}{query_num}
{self.batch_dir}
batch_{query_num}
{TEST_RESULTS}
${{SOME_NON_EXISTING_VARIABLE}}
{self.value_of_test_substitution_variable}"""
                self.assertEqual(text_compare, text_actual)

class TestNoTemplateFile(unittest.TestCase):
    def setUp(self):
        self.test_file = TEST_DIR+'/'+TEST_FILE
        self.test_tmpl = TEST_DIR+'/'+TEST_INV_TMPL
        self.test_res_dir = tempfile.mkdtemp()
        self.batch_dir = os.path.join(self.test_res_dir, 'batches')
        self.job_dir   = os.path.join(self.test_res_dir, 'jobs')
        self.proc = subprocess.run([TEST_CMD, self.test_file, '-l', TEST_BATCH_LENGTH,
            '-o', self.batch_dir, '-j', self.job_dir, '-t', self.test_tmpl],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE)

    def tearDown(self):
        shutil.rmtree(self.test_res_dir)

    def test(self):
        self.assertEqual(self.proc.returncode, 1)

class TestNoTestFile(unittest.TestCase):
    def setUp(self):
        self.test_file = TEST_DIR+'/'+TEST_FILE_NOT_EXIST
        self.test_tmpl = TEST_DIR+'/'+TEST_TMPL
        self.test_res_dir = tempfile.mkdtemp()
        self.batch_dir = os.path.join(self.test_res_dir, 'batches')
        self.job_dir   = os.path.join(self.test_res_dir, 'jobs')
        self.proc = subprocess.run([TEST_CMD, self.test_file, '-l', TEST_BATCH_LENGTH,
            '-o', self.batch_dir, '-j', self.job_dir, '-t', self.test_tmpl],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE)

    def tearDown(self):
        shutil.rmtree(self.test_res_dir)

    def test(self):
        self.assertEqual(self.proc.returncode, 2)

class TestNoPermissionToWrite(unittest.TestCase):
    def setUp(self):
        self.test_file = TEST_DIR+'/'+TEST_FILE
        self.test_tmpl = TEST_DIR+'/'+TEST_TMPL
        self.test_manifest = TEST_MANIFEST_AT_ROOT
        self.test_res_dir = tempfile.mkdtemp()
        self.batch_dir = os.path.join(self.test_res_dir, 'batches')
        self.job_dir   = os.path.join(self.test_res_dir, 'jobs')
        self.proc = subprocess.run([TEST_CMD, self.test_file, '-l', TEST_BATCH_LENGTH,
            '-o', self.batch_dir, '-j', self.job_dir, '-t', self.test_tmpl,
            '-m', self.test_manifest],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE)

    def tearDown(self):
        shutil.rmtree(self.test_res_dir)

    def test(self):
        self.assertEqual(self.proc.returncode, 3)

class TestGZipWithNoExtension(unittest.TestCase):
    def setUp(self):
        self.test_file = TEST_DIR+'/'+TEST_FILE_GZ
        self.test_tmpl = TEST_DIR+'/'+TEST_TMPL
        self.test_res_dir = tempfile.mkdtemp()
        self.batch_dir = os.path.join(self.test_res_dir, 'batches')
        self.job_dir   = os.path.join(self.test_res_dir, 'jobs')
        self.proc = subprocess.run([TEST_CMD, self.test_file, '-l', TEST_BATCH_LENGTH,
            '-o', self.batch_dir, '-j', self.job_dir, '-t', self.test_tmpl],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE)

    def tearDown(self):
        shutil.rmtree(self.test_res_dir)

    def test(self):
        self.assertEqual(self.proc.returncode, 4)

class TestGZipExtensionOnNotCompressedFile(unittest.TestCase):
    def setUp(self):
        self.test_file = TEST_DIR+'/'+TEST_FILE_NOT_GZ
        self.test_tmpl = TEST_DIR+'/'+TEST_TMPL
        self.test_res_dir = tempfile.mkdtemp()
        self.batch_dir = os.path.join(self.test_res_dir, 'batches')
        self.job_dir   = os.path.join(self.test_res_dir, 'jobs')
        self.proc = subprocess.run([TEST_CMD, self.test_file, '-l', TEST_BATCH_LENGTH,
            '-o', self.batch_dir, '-j', self.job_dir, '-t', self.test_tmpl],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE)

    def tearDown(self):
        shutil.rmtree(self.test_res_dir)

    def test(self):
        self.assertEqual(self.proc.returncode, 5)

class TestTarExtensionOnNotArchivedFile(unittest.TestCase):
    def setUp(self):
        self.test_file = TEST_DIR+'/'+TEST_FILE_NOT_TAR
        self.test_tmpl = TEST_DIR+'/'+TEST_TMPL
        self.test_res_dir = tempfile.mkdtemp()
        self.batch_dir = os.path.join(self.test_res_dir, 'batches')
        self.job_dir   = os.path.join(self.test_res_dir, 'jobs')
        self.proc = subprocess.run([TEST_CMD, self.test_file, '-l', TEST_BATCH_LENGTH,
            '-o', self.batch_dir, '-j', self.job_dir, '-t', self.test_tmpl],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE)

    def tearDown(self):
        shutil.rmtree(self.test_res_dir)

    def test(self):
        self.assertEqual(self.proc.returncode, 6)

class TestEmptyFile(unittest.TestCase):
    def setUp(self):
        self.test_file = TEST_DIR+'/'+TEST_FILE_EMPTY
        self.test_tmpl = TEST_DIR+'/'+TEST_TMPL
        self.test_res_dir = tempfile.mkdtemp()
        self.batch_dir = os.path.join(self.test_res_dir, 'batches')
        self.job_dir   = os.path.join(self.test_res_dir, 'jobs')
        self.proc = subprocess.run([TEST_CMD, self.test_file, '-l', TEST_BATCH_LENGTH,
            '-o', self.batch_dir, '-j', self.job_dir, '-t', self.test_tmpl],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE)

    def tearDown(self):
        shutil.rmtree(self.test_res_dir)

    def test(self):
        self.assertEqual(self.proc.returncode, 7)
