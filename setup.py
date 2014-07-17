
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
    'version': '0.4.0',
    'install_requires': ['paramiko', 'helperlib'],
    'dependency_links': [
        'git+https://github.com/bluec0re/python-helperlib.git#egg=helperlib'
    ],
    'packages': ['sftp_sync'],
    'scripts': ['bin/sftpsync'],
    'name': 'sftp_sync'
}

setup(**config)
