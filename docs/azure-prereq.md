## Setting Up Your Azure Environment

### Prerequisites
* An Azure account
* Azure CLI installed

### 1. Installing Azure CLI
You can install Azure CLI on various operating systems. Refer to the official documentation for detailed instructions: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows
```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

option) install kubectl using snap
```bash
sudo snap install kubectl --classic
```

### 2. Logging into Azure
To log in to your Azure account, use the following command:
```bash
az login --use-device-code
```
### 3. Checking Your Azure Subscription
```bash
az account show
```
This will display information about your current subscription, including the name, ID, and state.

### 4. Creating an Azure Container Registry(ACR)

```bash
# set variables
acr_resourcegroup=your_resource_group
acr_name=your_acr_name
location=koreacentral

# create a acr resource group
az group create --name $acr_resourcegroup --location $location

# create a acr
az acr create --resource-group $acr_resourcegroup --name $acr_name --sku Standard

```
The reason for creating an Azure Container Registry (ACR) is to deploy `docker-*` images located under the `/src` folder, which are required for processing jobs when ElasticBlast runs. The ACR will be used privately within the Azure Kubernetes Service (AKS) cluster by granting the necessary permissions.

### 5. Ubuntu Environment setup
This environment setup is tailored for Ubuntu 22.04. Windows users should install Ubuntu 22.04 on WSL and follow the configuration steps. If the environment is unstable, users can set up an Ubuntu 22.04 VM on Azure and follow the instructions there.
[environment.md](./environment.md)

### 6. Clone this Repo
Currently, ElasticBlast on Azure cannot be used directly with the command `pip install git+https://github.com/dotnetpower/elastic-blast-azure.git`. Since `ElasticBlast on Azure` needs to be set up in a private environment, the required Docker images must be deployed to your own ACR.
```bash
git clone https://github.com/dotnetpower/elastic-blast-azure.git
cd elastic-blast-azure
```

### 7. Push your own docker images to ACR
You need to update the value of `AZURE_REGISTRY?=elbacr.azurecr.io` in the Makefile of each Docker folder.  
Change it to the ACR name you set in step 4.
example: AZURE_REGISTRY?=youracr.azurecr.io 

Now, You can push the image to acr
```bash
# Navigate to the `docker-blast` folder:  
cd docker-blast
make azure-build
```
Let's apply the same changes to the following folders as well.
docker-blast, docker-job-submit, docker-openapi, docker-qs

Once you have completed these steps, you can verify the list of repositories in ACR using the following command.
```bash
az acr repository list --name elbacr
```
```console
[
  "elb-openapi",
  "ncbi/elasticblast-job-submit",
  "ncbi/elasticblast-query-split",
  "ncbi/elb"
]
```

### 8. Make an Azure Storage Account
```bash
# set variables
resourcegroup=your_resource_group
sa_name=your_storage_account_name
location=koreacentral

# create your storage account
az storage account create --resource-group $resourcegroup --name $sa_name$ --hns true --location $location$ --sku Standard_LRS
```
Now that the Storage Account has been created, let's upload the required databases from NCBI to the `/blast-db` container in the created Storage Account.

### 9. prepare the config file filename.ini
```ini
# https://github.com/ncbi/elastic-blast-demos/blob/master/elastic-blast-rdrp.ipynb

[cloud-provider]
azure-region=koreacentral
azure-acr-resource-group=rg-elbacr
azure-acr-name=elbacr
azure-resource-group=rg-elb-koc
azure-storage-account=stgelb
azure-storage-account-container=blast-db
azure-storage-account-key=your-storage-account-key # redefine on the .env file

[cluster]
name = elastic-blast
machine-type = Standard_E16s_v3
num-nodes = 3
exp-use-local-ssd = true
reuse = true

[blast]
program = blastx
db = https://stgelb.blob.core.windows.net/blast-db/wolf18/RNAvirome.S2.RDRP
queries = https://stgelb.blob.core.windows.net/queries/JAIJZY01.1.fsa_nt.gz
results = https://stgelb.blob.core.windows.net/results
options = -task blastx-fast -evalue 0.01 -outfmt "7 std qcovs sskingdoms ssciname"

```

### 10. Activate the virtual environment
Set up a virtual environment and install the required packages.
```bash
virtualenv venv
source venv/bin/activate
pip install -r requirements/test.txt
```

Now that the database and config file are ready, you can submit the job following the NCBI documentation: [ElasticBlast Quickstart for GCP](https://blast.ncbi.nlm.nih.gov/doc/elastic-blast/quickstart-gcp.html#run-elasticblast).

> [!Note]
> Run the command `export AZURE_STORAGE_ACCOUNT_KEY=<your storage account key>` before executing the submit command.

## VSCode remote configuration
```bash
sudo apt-get install openssh-server
sudo apt-get install sshfs
```

## Known Issues

### Storage Account Networking
Enable `Enabled from all networks` if you don't have private network

### Storage Account Configuration
Enable `Allow storage account key access`

### Invalid base64-encoded exception
to avoid `azure.storage.blob._shared.authentication.AzureSigningError: Invalid base64-encoded string: number of data characters (41) cannot be 1 more than a multiple of 4` error, you need set the env variable. not using .env file.
export AZURE_STORAGE_ACCOUNT_KEY=<your storage account key>


