from setuptools import setup, find_packages

with open("./README.md") as f:
    readme = f.read()

with open("./LICENSE") as f:
    license = f.read()

setup(
    name="aioservicekit",
    version="0.2.2",
    description="A framework for creating asynchronous services. It helps to create nanoservices (like microservices, but for microservices), control their life cycle and organize communications.",
    long_description=readme,
    long_description_content_type="text/markdown",
    license=license,
    author="Bohdan Kushnir",
    author_email="",
    url="https://github.com/8ByteCore8/aioservicekit",
    packages=find_packages(exclude=["tests", "examples"]),
    python_requires=">=3.6",
)
