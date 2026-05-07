from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

setup(
    name="dental_clinic",
    version="0.0.1",
    description="Custom dental clinic inventory management for Drs. Nicolas & Asp",
    author="Apollonia Health",
    author_email="itmg@nicolasasp.ae",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
