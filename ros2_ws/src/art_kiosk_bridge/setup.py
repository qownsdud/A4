# [파일 역할] ROS 2 패키지 art_kiosk_bridge 설치/실행 등록 설정
from glob import glob
from setuptools import setup

package_name = 'art_kiosk_bridge'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='A4 Team',
    maintainer_email='maintainer@example.invalid',  # TEAM_SYNC(PM): release metadata
    description='Independent HTTP-to-ROS 2 kiosk bridge',
    license='UNLICENSED',  # TEAM_SYNC(PM): choose license before sharing
    entry_points={
        'console_scripts': [
            'bridge = art_kiosk_bridge.main:main',
        ],
    },
)
