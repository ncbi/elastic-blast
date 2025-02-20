import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import uvicorn
from util import safe_exec
import subprocess
import configparser

app = FastAPI()

@app.get("/")
async def read_root():
    return {"message": "Hello, FastAPI with Nginx!"}

@app.get('/ping')
async def ping():
    return {"message": "pong"}

@app.get('/aks_status')
async def get_aks_status():
    cmd = f'kubectl get nodes'
    proc = str(safe_exec(cmd).stdout)
    proc = proc.replace('\\n', '<br>')
    return {"message": proc}

@app.get('/elb_status')
async def elb_status():
    cmd = f'elastic-blast --help'
    proc = str(safe_exec(cmd).stdout)
    proc = proc.replace('\\n', '<br>')
    return {"message": proc}

FILE_DIRECTORY = "/app"

# return azure storage files from filename
@app.get('/result/{filename}')
async def get_result_file(filename: str):
    
    try:
        cmd = 'azcopy login --identity'
        safe_exec(cmd)
            
        cmd = f'azcopy cp https://stgelb.blob.core.windows.net/results/* . --include-pattern=*{filename}*'
        safe_exec(cmd)
        
        cmd = f'zip {filename}.zip *{filename}*'
        safe_exec(cmd)
    except Exception as e:
        return JSONResponse(content={"message": f"Error: {e}"}, status_code=500)
    
    # return the zip file if it exists
    if os.path.exists(f'{filename}.zip'):
        return FileResponse(f'{filename}.zip')
    else:
        return JSONResponse(content={"message": "No file found"}, status_code=404)

@app.get('/elb_config')
async def get_elb_config():
    try:
        cmd = 'azcopy login --identity'
        safe_exec(cmd)
            
        cmd = f'azcopy cp https://stgelb.blob.core.windows.net/results/metadata/elastic-blast-config.json .'
        safe_exec(cmd)
        
        # read the config file
        with open('elastic-blast-config.json', 'r') as f:
            data = f.read()
            
        return JSONResponse(content={"message": data})
        
    except Exception as e:
        return JSONResponse(content={"message": f"Error: {e}"}, status_code=500)

class Blast(BaseModel):
    program: str = 'blastn'
    db: str
    queries: str
    results: str
    options: str
    
# run elasticblast with post data {"cfg": "elastic-blast.ini"}
@app.post('/submit')
async def submit(Blast: Blast):
    try:
        # cmd = 'azcopy login --identity'
        # safe_exec(cmd)
        
        # elg-cfg.ini 파일을 읽어서 Blast 에 설정된 값으로 replace 후 cfg.ini 파일로 저장
        # config = configparser.ConfigParser()
        # config.read("elb-cfg.ini", encoding='utf-8')
        
        
        # config['blast']['program'] = Blast.program
        # config['blast']['db'] = Blast.db
        # config['blast']['queries'] = Blast.queries
        # config['blast']['results'] = Blast.results
        # config['blast']['options'] = Blast.options
        # with open("elastic-blast.ini", "w") as configfile:
        #     config.write(configfile)
                    
        # cmd = f'elastic-blast submit --cfg elastic-blast.ini'
        cmd = f'elastic-blast submit --cfg elb-cfg.ini'
        process = subprocess.Popen(cmd.split(' '), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        return JSONResponse(content={"message": "submit job started"})
    except Exception as e:
        return JSONResponse(content={"message": f"Error: {e}"}, status_code=500)

    


if __name__ == '__main__':

    uvicorn.run(f"{Path(__file__).stem}:app", host="127.0.0.1", port=8000, reload=True)

    
