from setuptools import setup, find_packages
import os

version = '0.1'

setup(name='treegital.uploader',
      version=version,
      description="Uploading application/service",
      long_description=open("README.txt").read() + "\n" +
                       open(os.path.join("docs", "HISTORY.txt")).read(),
      classifiers=[
        "Programming Language :: Python",
        ],
      keywords='',
      author='',
      author_email='',
      license='ZPL',
      package_dir={'': 'src'},
      packages=find_packages('src'),
      include_package_data=True,
      namespace_packages=['treegital'],
      zip_safe=False,
      install_requires=[
          'setuptools',
      ],
      entry_points={
          'paste.app_factory': [
              'uploader = treegital.uploader.service:upload_service',
              ],
          },
      )
