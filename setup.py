from setuptools import setup, find_packages

setup(
    name='polarnav',
    version='0.1.0',
    description='AI-Enabled Antarctic Sea-Ice, Iceberg Trajectory, and Navigation Decision Support System',
    author='SIH 2026 Team',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    python_requires='>=3.10',
    install_requires=[
        'fastapi>=0.110.0',
        'uvicorn>=0.28.0',
        'pydantic>=2.6.0',
        'numpy>=1.26.0',
        'scipy>=1.12.0',
    ],
    entry_points={
        'console_scripts': [
            'polarnav=cli:main',
        ],
    },
)
