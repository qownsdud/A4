from setuptools import find_packages, setup

package_name = 'collaborate1'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    package_data={
        package_name: ['*.svg'],
    },
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='qownsdud',
    maintainer_email='qownsdud@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'drawingtest_force = collaborate1.drawingtest_force:main',
            'drawingtest_slow = collaborate1.drawingtest_slow:main',
            'grip_test = collaborate1.grip_text:main',
            'force_test = collaborate1.force_test:main',
            'pendant_force_monitor = collaborate1.pendant_force_monitor:main',
            'draw_line = collaborate1.draw_line:main',
            'move_test = collaborate1.move_test:main',
            'draw_square = collaborate1.draw_square:main',
            'draw_path = collaborate1.draw_path:main',
            'force_control_test = collaborate1.force_control_test:main',
            'force_compare = collaborate1.force_compare:main',

        ],
    },
)
