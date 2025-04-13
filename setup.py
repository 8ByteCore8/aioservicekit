from setuptools import find_packages, setup

with open("./README.md") as f:
    readme = f.read()

with open("./LICENSE") as f:
    license = f.read()

setup(
    name="aioservicekit",
    version="0.5.0",
    keywords=[
        "async",
        "asyncio",
        "service",
    ],
    description="A framework for creating asynchronous services. It helps to create nanoservices (like microservices, but for microservices), control their life cycle and organize communications.",
    use_scm_version=True,
    long_description=readme,
    long_description_content_type="text/markdown",
    license=license,
    author="Bohdan Kushnir",
    requires=["exceptiongroup"],
    extras_require={
        "test": [
            "ruff>=0.7.4",
        ],
    },
    author_email="",
    setup_requires=[
        "setuptools_scm",
    ],
    url="https://github.com/8ByteCore8/aioservicekit",
    project_urls={
        "Source": "https://github.com/8ByteCore8/aioservicekit",
    },
    packages=find_packages(exclude=["tests", "examples"]),
    python_requires=">=3.6",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
)
