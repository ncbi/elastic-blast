import os
import logging
import subprocess
from typing import List, Union, Callable, Optional, Dict


def safe_exec(cmd: Union[List[str], str], env: Optional[Dict[str, str]] = None, timeout: Optional[float] = 60) -> subprocess.CompletedProcess:
    """Wrapper around subprocess.run that raises SafeExecError on errors from
    command line with error messages assembled from all available information

    Arguments:
        cmd: Command line
        env: Environment variables to set. Current environment will also be
        copied. Variables in env take priority if they appear in both
        os.environ and env.
    """
    if isinstance(cmd, str):
        cmd = cmd.split()
    if not isinstance(cmd, list):
        raise ValueError('safe_exec "cmd" argument must be a list or string')

    run_env = None
    if env:
        run_env = os.environ | env
    try:
        logging.debug(' '.join(cmd))
        if env:
            logging.debug(env)
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=run_env, universal_newlines=True, timeout=timeout)
        
    except subprocess.CalledProcessError as e:
        msg = f'The command "{" ".join(e.cmd)}" returned with exit code {e.returncode}\n{handle_error(e.stderr)}\n{handle_error(e.stdout)}'
        if e.output is not None:
            '\n'.join([msg, f'{handle_error(e.output)}'])
            raise Exception(e.returncode, msg)
    except Exception as e:
        raise Exception(e.errno, str(e))
   
    return p

def handle_error(exp_obj):
    """Handle error and decode stderr if necessary."""
    
    if isinstance(exp_obj, bytes):
        exp_obj = exp_obj.decode()
    return exp_obj