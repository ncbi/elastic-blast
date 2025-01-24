from setuptools import setup


# setup(setup_requires='packit', packit=True)
setup(setup_requires='packit', packit=True, include_package_data=True, package_data={'': ['templates/*.*']})