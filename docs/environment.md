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

update & upgrade apt
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

you can set python3 as python using alias when python version is not 3.11
```bash
alias python=python3
```

install venv
```bash
python -m pip install --user -U virtualenv
```



