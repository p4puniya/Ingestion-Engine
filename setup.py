from setuptools import setup, find_packages

setup(
    name="ingestai",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "click",
        "fastapi",
        "uvicorn[standard]",
        "requests",
        "beautifulsoup4",
        "pdfplumber",
        "python-frontmatter",
        "markdownify",
        "trafilatura",
        "mistune",
    ],
    entry_points={
        "console_scripts": [
            "ingestai=app:cli",
        ],
    },
) 