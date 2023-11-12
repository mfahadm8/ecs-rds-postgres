import setuptools

with open("README.md") as fp:
    long_description = fp.read()


def __read_cdk_version() -> str:
    f = open("cdk.version")
    return f.read()


CDK_VERSION = __read_cdk_version()

setuptools.setup(
    name="cdk_template",
    version="0.0.1",
    description="Cloud Central Solution CDK App for TheDB",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Muhammad Fahad Mustfa",
    install_requires=[
        "aws-cdk-lib==" + CDK_VERSION,
        "constructs>=10.0.0,<11.0.0",
        "python-benedict==0.22.4",
    ],
    python_requires=">=3.6",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: JavaScript",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Topic :: Software Development :: Code Generators",
        "Topic :: Utilities",
        "Typing :: Typed",
    ],
)
