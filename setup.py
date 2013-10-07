
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

config = {
    'description': 'Script for syncing a remote directory via sftp (with basic version control)',
    'author': 'Timo Schmid',
    'url': 'https://github.com/bluec0re/python-sftpsync',
    'download_url': 'https://github.com/bluec0re/python-sftpsync/archive/master.zip',
    'author_email': 'coding@bluec0re.eu',
    'version': '0.1.3',
    'install_requires': ['paramiko'],
    'packages': ['sftp_sync'],
    'scripts': ['bin/sftpsync'],
    'name': 'sftp_sync'
}

setup(**config)
