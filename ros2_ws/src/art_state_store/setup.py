from setuptools import setup

package_name = "art_state_store"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    package_data={package_name: ["schema.sql"]},
    include_package_data=True,
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=False,
    maintainer="A4 Team",
    maintainer_email="maintainer@example.invalid",
    description="A4 SQLite 영속 상태 저장소 및 실시간 웨이포인트 버퍼 패키지",
    license="UNLICENSED",
)
