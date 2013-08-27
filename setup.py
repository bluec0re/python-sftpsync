
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

config = {
    'description': 'Script for syncing a remote directory via sftp (with basic version control)',
    'author': 'Timo Schmid',
    'url': 'URL to get it at.',
    'download_url': 'Where to download it.',
    'author_email': 'coding@bluec0re.eu',
    'version': '0.1',
    'install_requires': ['paramiko'],
    'packages': ['sftp_sync'],
    'scripts': ['bin/sftpsync'],
    'name': 'sftp_sync'
}

setup(**config)
