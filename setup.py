from setuptools import setup

setup(name='pyrenode',
      version='0.2',
      description='Very basic Python lib to talk to Renode',
      author='Antmicro',
      author_email='mgielda@antmicro.com',
      install_requires=[
          'pexpect', 'dataclasses', 'psutil', 'robotframework==4.0.1'
      ],
      license='MIT',
      packages=['pyrenode'])
