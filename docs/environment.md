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

# AZ cli install
```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

Now You will need to configure aws configure until your project is fully Azure-enabled.





