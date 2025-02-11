# Upgrade python 3.10 to 3.11 on Ubuntu 22.04

check python version on your Ubuntu 22.04
```bash
python --version
python3 --version
```

add repository to download python 3.11
```bash
sudo add-apt-repository ppa:deadsnakes/ppa
```

update & upgrade apt (it takes 3~5 minutes.)
```bash
sudo apt update
sudo apt upgrade
```

Install python 3.11
```bash
sudo apt-get install python3.11
```

check versions
```bash
python3 --version
python3.11 --version
```

update alternatives
```bash
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 2

sudo update-alternatives --config python3
```

set python as python3
```bash
sudo apt install python-is-python3
python --version
```

install pip
```bash
sudo apt install python3-pip
```

check python & pip version
```bash
python --version
pip --version
```

install venv
```bash
python -m pip install --user -U virtualenv
```

# AWS cli install

download AWS CLI Installer
```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
```

install unzip package & unzip
```bash
sudo apt install unzip
unzip awscliv2.zip
```

run Installer
```bash
sudo ./aws/install
```

verify the installation
```bash
aws --version
```

# GSUtil install
```bash
sudo snap install google-cloud-cli --classic
```

# AZ cli install
```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

install kubectl using snap
```bash
sudo snap install kubectl --classic
```

Now You will need to configure aws configure until your project is fully Azure-enabled.


## for debugging

build package and install package
```bash
pip install pytest
pip uninstall elastic-blast -y; python setup.py sdist bdist_wheel; pip install dist/elastic_blast-0.0-py3-none-any.whl;
```


# azcopy - https://gist.github.com/aessing/76f1200c9f5b2b9671937b3b0ed5fd6f

# Download and extract
wget https://aka.ms/downloadazcopy-v10-linux
tar -xvf downloadazcopy-v10-linux

# Move AzCopy
sudo rm -f /usr/bin/azcopy
sudo cp ./azcopy_linux_amd64_*/azcopy /usr/bin/
sudo chmod 755 /usr/bin/azcopy

# Clean the kitchen
rm -f downloadazcopy-v10-linux
rm -rf ./azcopy_linux_amd64_*/

# install docker
```bash
sudo apt update
sudo apt install -y apt-transport-https ca-certificates curl software-properties-common

curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io

sudo service docker start

sudo usermod -aG docker $USER

docker --version

```
