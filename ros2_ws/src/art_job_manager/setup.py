from setuptools import find_packages, setup

setup(
    name="art_job_manager",
    version="0.1.0",
    packages=find_packages(),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/art_job_manager"]),
        ("share/art_job_manager", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=False,
    maintainer="A4 Team",
    maintainer_email="maintainer@example.invalid",
    description="SQLite와 분리된 순수 인메모리 중앙 작업 제어 패키지",
    license="UNLICENSED",
    entry_points={
        "console_scripts": [
            "job_manager = art_job_manager.job_manager_node:main",
        ],
    },
)
