# Copyright (c) 2019-2020 Thomas Kramer.
# SPDX-FileCopyrightText: 2022 Thomas Kramer
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from setuptools import setup, find_packages


def readme():
    with open("README.md", "r") as f:
        return f.read()


setup(name='lctime',
      version='0.0.18',
      description='CMOS standard-cell characterization kit.',
      long_description=readme(),
      long_description_content_type="text/markdown",
      keywords='cmos cell characterization vlsi asic',
      classifiers=[
          'License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)',
          'Development Status :: 3 - Alpha',
          'Topic :: Scientific/Engineering',
          'Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)',
          'Programming Language :: Python :: 3'
      ],
      url='https://codeberg.org/librecell/lctime',
      author='T. Kramer',
      author_email='code@tkramer.ch',
      license='AGPL-3.0-or-later',
      packages=find_packages(),
      package_data={'': ['examples/*', 'test_data/*']},
      entry_points={
          'console_scripts': [
              'libertyviz = lctime.liberty.visualize:main_plot_timing',
              'libertymerge = lctime.liberty.merge:main',
              # 'lcsize = lctime.transistor_sizing.width_opt:main',
              'lctime = lctime.characterization.main_lctime:main',
              'sp2bool = lctime.characterization.main_sp2bool:main'
          ]
      },
      install_requires=[
          'klayout>=0.27.3', # GPLv3
          'numpy==1.0',  # BSD
          'sympy==1.6',  # BSD
          'matplotlib>=3.0',
          'networkx>=2.5',  # BSD
          'pyspice>=1.4',  # GPLv3
          'scipy>=1.5',  # BSD
          'liberty-parser>=0.0.15',  # GPLv3
          'joblib>=0.14', # BSD-3-Clause
      ],
      zip_safe=False)
