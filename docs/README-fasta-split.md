# fasta_split 

Splits large FASTA file into several files of approximately same size.

It does not split file mid-sequence, so all sequences are preserved in the final file set.

The original file can be from local file system, from GCP's GS file system, or accessible
from HTTP(S) or FTP URL.

The file can be GZIPped, or a set of files can be archived by TAR and optionally compressed
by GZIP or BZIP2. Set of files in TAR is interpreted as if it is merged in one large file.

The destination for all of the generated files (batches, jobs, and manifest) can be either
local or GS file system.

It generates job description files from template by substituting variables in the text
of the template.

All jobs are listed in manifest file which by default is written to STDOUT.

    $./fasta_split -h
    usage: fasta_split [-h] [-l BATCH_LEN] [-o OUTPUT] [-r RESULTS] [-j JOB_PATH]
                       [-t TEMPLATE] [-m MANIFEST]
                       inputSplit FASTA filepositional arguments:
      input                 input FASTA file, possible gzippedoptional arguments:
      -h, --help            show this help message and exit
      -l BATCH_LEN, --batch_len BATCH_LEN
                            batch length
      -o OUTPUT, --output OUTPUT
                            output path for batch FASTA files
      -r RESULTS, --results RESULTS
                            output path for BLAST results
      -j JOB_PATH, --job_path JOB_PATH
                            output path for job YAML files
      -t TEMPLATE, --template TEMPLATE
                            YAML template
      -m MANIFEST, --manifest MANIFEST
                            manifest file to write

The script substitutes the following variables in template YAML file while generating job YAML files.
Assuming the script writes a specific batch file as gs://path_to_input/batch_000.fa and
results parameter is 'path_to_results':

    {QUERY} - batch_000
    {QUERY_FQN} - gs://path_to_input/batch_000.fa
    {QUERY_PATH} - gs://path_to_input
    {QUERY_NUM} - 000
    {RESULTS} - path_to_results
