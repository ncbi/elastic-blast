## Setting Up Your Azure Environment

### Prerequisites
* An Azure account
* Azure CLI installed

### 1. Installing Azure CLI
You can install Azure CLI on various operating systems. Refer to the official documentation for detailed instructions: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows

### 2. Logging into Azure
To log in to your Azure account, use the following command:
```bash
az login
```
### 3. Checking Your Azure Subscription
```bash
az account show
```
This will display information about your current subscription, including the name, ID, and state.

### 4. Creating an Azure AD Application - no need

```bash
subscription_id=$(az account show --query id -o tsv)
az ad sp create-for-rbac --name "elastic-blast-app" --role Contributor --scopes /subscriptions/$subscription_id
```
You can change the name if you already have an app with the same name.

This command will create a service principal and assign the Contributor role to it within the specified resource group. You will get an output similar to this:
```json
{
  "appId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "displayName": "myApp",
  "password": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "tenant": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```
According to our findings, the `appId` should be assigned to the environment variable `AZURE_CLIENT_ID` within the .env file. Similarly, the `password` should be set as the value for `AZURE_CLIENT_SECRET` and the `tenant` should be set as the value for `AZURE_TENANT_ID`.

We are currently using app registration to generate SAS tokens for accessing storage. This approach allows our application to authenticate and authorize access to storage resources. However, we anticipate transitioning to managed identities in the future to streamline the authentication process and enhance security.


to avoid `azure.storage.blob._shared.authentication.AzureSigningError: Invalid base64-encoded string: number of data characters (41) cannot be 1 more than a multiple of 4` error, you need set the env variable. not using .env file.
export AZURE_STORAGE_ACCOUNT_KEY=<your storage account key>


