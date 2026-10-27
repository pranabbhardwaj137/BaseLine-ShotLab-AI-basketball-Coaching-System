from setuptools import setup, find_packages

setup(
    name="basketball-shot-lab",
    version="1.0.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
)
