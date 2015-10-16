#!/usr/bin/env python

import os
import sys
import setuptools.command.egg_info as egg_info_cmd
import shutil

from setuptools import setup, find_packages

SETUP_DIR = os.path.dirname(__file__)
README = os.path.join(SETUP_DIR, 'README')

setup(name='cwl2script',
      version='1.0',
      description='Compile Common Workflow Languge to shell script',
      long_description=open(README).read(),
      author='Common workflow language working group',
      author_email='common-workflow-language@googlegroups.com',
      url="https://github.com/common-workflow-language/cwl2script",
      download_url="https://github.com/common-workflow-language/cwl2script",
      license='Apache 2.0',
      py_modules=["cwl2script"],
      install_requires=[
          'cwltool >= 1.0.20151013135545'
        ],
      entry_points={
          'console_scripts': [ "cwl2script=cwl2script:main" ]
      },
      zip_safe=True
)
