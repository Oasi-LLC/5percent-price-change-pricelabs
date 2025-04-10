from setuptools import setup, find_packages

setup(
    name="pricelabs_tool",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "click>=8.0.0",
        "requests>=2.25.0",
        "python-dotenv>=0.19.0",
    ],
    entry_points={
        'console_scripts': [
            'pricelabs_tool=pricelabs_tool.__main__:cli',
        ],
    },
) 