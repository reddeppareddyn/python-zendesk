from setuptools import setup, find_packages
 
setup(
    name='zendesk',
    version='0.1',
    author='Reddeppa Reddy',
    author_email='reddy.reddyn@gmail.com',
    packages = find_packages('.'),
    package_dir = {'': '.'},
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
    ],
    zip_safe=True,
)
