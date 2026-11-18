from setuptools import setup, find_packages
setup(name='art_drawing_controller', version='0.3.0', packages=find_packages(),
 data_files=[('share/ament_index/resource_index/packages',['resource/art_drawing_controller']),('share/art_drawing_controller',['package.xml'])],
 package_data={'art_drawing_controller':['static/*']}, install_requires=['setuptools'], zip_safe=False,
 maintainer='A4 Team',maintainer_email='maintainer@example.invalid',description='A4 art_drawing_controller',license='UNLICENSED',
 entry_points={'console_scripts':['drawing_controller = art_drawing_controller.drawing_node:main', 'import_equipment_profile = art_drawing_controller.equipment_settings:main']})
