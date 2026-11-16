from setuptools import find_packages, setup

package_name = 'rokey1'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    package_data={
        'rokey1': ['*.svg'],
    },
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='BL',
    maintainer_email='mail@mail.com',
    description='TODO: Package description',
    license='MIT',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'simple_move = rokey1.move:main',
            'grip_test = rokey1.grip_text:main',
            'gear = rokey1.gear:main',
            'drawing_test1 = rokey1.drawingtest1:main',
            'drawing_ryu = rokey1.drawingtest_ryu:main',
        ],
    },
)
