import os
import yaml
from setuptools import find_packages, setup

package_name = 'collaborate1'
here = os.path.dirname(os.path.abspath(__file__))


def load_console_scripts() -> list[str]:
    """config/registry.yaml에서 console_scripts 엔트리포인트를 읽어 생성한다."""
    registry_path = os.path.join(here, 'config', 'registry.yaml')
    with open(registry_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    scripts = []
    for group in (data.get('nodes') or {}).values():
        if not isinstance(group, dict):
            continue
        for node_name, meta in group.items():
            if isinstance(meta, dict) and meta.get('entry'):
                scripts.append(f"{node_name} = {meta['entry']}")
    return scripts


setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    package_data={
        f'{package_name}.core': ['*.svg'],
        f'{package_name}.test_image': ['*.json', '*.svg', '*.png'],
    },
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/registry.yaml']),
        ('share/' + package_name + '/test_image', [
            'collaborate1/test_image/test_image_strokes.json',
            'collaborate1/test_image/test_image.svg',
            'collaborate1/test_image/test_image.png',
        ]),
    ],
    install_requires=['setuptools', 'PyYAML'],
    zip_safe=True,
    maintainer='qownsdud',
    maintainer_email='qownsdud@todo.todo',
    description='M0609 + RG2 collaborative drawing and pen pick-and-place package',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': load_console_scripts(),
    },
)
