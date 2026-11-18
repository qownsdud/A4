# [파일 역할] ROS 2에서 `ros2 run art_job_manager 실행이름`을 가능하게 하는 설치 설정
# 기본 `job_manager`는 실제 Action Client, `job_manager_test`는 구형 시뮬레이션 노드입니다.
from setuptools import setup

package_name = 'art_job_manager'

setup(
    name=package_name,
    version='0.2.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='A4 Team',
    maintainer_email='maintainer@example.invalid',  # TEAM_SYNC(PM): set official contact.
    description='Persistent A4 ROS 2 JobManager with optional real ROS Action controller',
    license='UNLICENSED',  # TEAM_SYNC(PM): agree on release license.
    # console_scripts의 좌측 이름이 `ros2 run`의 마지막 인자입니다.
    entry_points={'console_scripts': [
        'job_manager = art_job_manager.job_manager_node:main',
        'job_manager_test = art_job_manager.job_manager_test_node:main',
    ]},
)
